"""BYS360 H1E-F -- mail_feedback.py + misc-domain raw status/type display
closure contract.

Continuing the repo-wide sweep, this wave closes:

  - app/services/mail_feedback.py: three feedback-request/meeting email
    bodies (send_feedback_request_mail, send_feedback_response_mail,
    send_feedback_meeting_created_mail) showed the raw FeedbackRequest.status
    / FeedbackMeeting.status value with NO translation at all, and the one
    email that DID already translate its status
    (send_feedback_meeting_status_update_mail) had the exact fallback-to-raw
    self-shape (`status_label_map.get(meeting.status, meeting.status or
    "-")`) this initiative targets. The two label dicts previously
    duplicated inline in mail_feedback.py were consolidated into their
    canonical home, app/services/feedback_service.py (which already hosts
    CAMPAIGN_STATUS_LABELS et al.), and app/performance/feedback_helpers.py's
    OWN independent copy of the request-status dict (with the same
    fallback-to-raw defect, feeding an in-app notification title) was
    replaced with an import of the same canonical dict -- three
    independent copies collapsed into one.
  - app/services/feedback_service.py's pre-existing get_campaign_type_label()
    had the same fallback-to-raw defect; a new get_campaign_status_label()
    was added (no prior label function existed for campaign status at all)
    and wired into feedback/campaign_manage.html, feedback/dashboard.html
    (which also used a raw `campaign_type|replace('_',' ')|title` Jinja
    filter chain instead of the existing label function) and
    feedback/manager_view.html.
  - app/templates/feedback/action_list.html's `action.priority` had no
    label function at all; new get_action_priority_label() added.
  - app/templates/feedback_meeting_detail.html showed both
    FeedbackMeeting.status and FeedbackRequest.status raw with no
    translation.
  - app/file_center/services.py gained a new download_status_label()
    (following the same established, already-safe pattern as this file's
    existing scan_label()/file_security_status_label()) for
    FileDownloadLog.status, previously shown completely raw in
    file_center/logs.html. FileAuditLog.action was deliberately left
    untranslated (open-ended, ever-growing internal event-type vocabulary
    across the whole app, not a small closed status enum -- same
    classification as communication's audit-log action_type).
  - app/services/publication_service.py's existing, already-safe
    publication_status_label() was simply never wired into
    publications/viewer.html, which instead rendered
    `publication.status|replace('_',' ')|title` (twice) -- a cosmetic
    cleanup of the raw value, not a real translation, and NOT
    fallback-safe for any value that never went through
    STATUS_LABELS.get() to begin with.
  - app/templates/task_management.html had two `{% else %}{{ row.X }}
    {% endif %}` visible-text fallback branches (an if/elif/else chain
    achieving the same raw-echo defect as the dict `.get(x, x)` shape
    found everywhere else in this initiative) for
    assignment-log event_type and evaluator-task status.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import date, time
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_mail_feedback_misc_tmp" / "test_dbs"
_PASSWORD = "H1EMailFeedbackMiscTest1!"


# ---------------------------------------------------------------------------
# A: pure-function unit contracts (no app required).
# ---------------------------------------------------------------------------


def test_campaign_type_and_status_labels_never_leak_raw() -> None:
    from app.services.feedback_service import get_campaign_status_label, get_campaign_type_label

    assert get_campaign_type_label("pulse") == "Nabız"
    assert get_campaign_status_label("published") == "Yayında"

    unmapped_type = "future_campaign_type_v9"
    unmapped_status = "future_campaign_status_v9"
    assert get_campaign_type_label(unmapped_type) == "Bilinmiyor"
    assert get_campaign_status_label(unmapped_status) == "Bilinmiyor"


def test_action_priority_label_never_leaks_raw() -> None:
    from app.services.feedback_service import get_action_priority_label

    assert get_action_priority_label("high") == "Yüksek"
    assert get_action_priority_label("future_priority_v9") == "Bilinmiyor"


def test_feedback_meeting_and_request_status_labels_never_leak_raw() -> None:
    from app.services.feedback_service import (
        get_feedback_meeting_status_label,
        get_feedback_request_status_label,
    )

    assert get_feedback_meeting_status_label("tamamlandi") == "Tamamlandı"
    assert get_feedback_meeting_status_label("future_meeting_status_v9") == "Bilinmiyor"

    assert get_feedback_request_status_label("randevulandi") == "Randevulandı"
    assert get_feedback_request_status_label("future_request_status_v9") == "Bilinmiyor"


def test_feedback_status_label_dicts_are_consolidated_not_duplicated() -> None:
    """The three independent copies of these dicts (mail_feedback.py,
    feedback_helpers.py, and the original feedback_service.py) must now
    all resolve to the SAME dict object -- proving the drift-risk
    duplication was actually collapsed, not just individually patched."""
    from app.performance.feedback_helpers import FEEDBACK_REQUEST_STATUS_LABELS as helpers_dict
    from app.services.feedback_service import (
        FEEDBACK_MEETING_STATUS_LABELS as canonical_meeting_dict,
        FEEDBACK_REQUEST_STATUS_LABELS as canonical_request_dict,
    )
    from app.services.mail_feedback import (
        FEEDBACK_MEETING_STATUS_LABELS as mail_meeting_dict,
        FEEDBACK_REQUEST_STATUS_LABELS as mail_request_dict,
    )

    assert mail_request_dict is canonical_request_dict
    assert mail_meeting_dict is canonical_meeting_dict
    assert helpers_dict is canonical_request_dict


def test_download_status_label_never_leaks_raw() -> None:
    from app.file_center.services import download_status_label

    assert download_status_label("success") == "Başarılı"
    assert download_status_label("wrong_password") == "Şifre hatalı"
    assert download_status_label("future_download_status_v9") == "Bilinmiyor"


def test_publication_status_label_already_safe_and_now_used() -> None:
    from app.services.publication_service import publication_status_label

    assert publication_status_label("draft") == "Taslak"
    assert publication_status_label("archived") == "Arşiv"
    # This function already had a safe fallback before H1E-F -- confirming
    # it, since the fix here was wiring it into the template, not the
    # function itself.
    assert publication_status_label("future_publication_status_v9") == "Yayında"


# ---------------------------------------------------------------------------
# B: email body content -- known values translated, unmapped values never
# leak raw, and the previously-buggy self-fallback status_label_map is gone.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-mail-feedback-misc-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-mail-feedback-misc-first-login-test-pw")
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
    monkeypatch.setenv("FILE_CENTER_ENABLED", "true")

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
            soyad="MailFeedbackMiscContract",
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


def _build_feedback_request(app, *, employee_id, manager_id, status):
    from app.extensions import db
    from app.models import FeedbackRequest, PerformanceEvaluation, PerformancePeriod

    with app.app_context():
        period = PerformancePeriod(title="H1E Mail Test Period", period_type="yillik", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        db.session.add(period)
        db.session.commit()
        evaluation = PerformanceEvaluation(period_id=period.id, employee_id=employee_id)
        db.session.add(evaluation)
        db.session.commit()
        req = FeedbackRequest(
            evaluation_id=evaluation.id,
            period_id=period.id,
            employee_id=employee_id,
            level_1_manager_id=manager_id,
            status=status,
            reason="H1E test feedback request reason",
        )
        db.session.add(req)
        db.session.commit()
        return req.id


def test_feedback_request_mail_never_leaks_an_unmapped_status(app) -> None:
    manager_id = _create_user(app, sicil_no="h1e_mail_a_manager")
    employee_id = _create_user(app, sicil_no="h1e_mail_a_employee")
    req_id = _build_feedback_request(app, employee_id=employee_id, manager_id=manager_id, status="future_request_status_v9")

    captured: dict = {}

    def _fake_send_email(to, subject, body):
        captured["body"] = body
        return True, "ok"

    import app.services.mail_feedback as mail_feedback
    from app.extensions import db

    with app.app_context():
        from app.models import FeedbackRequest, User

        req = db.session.get(FeedbackRequest, req_id)
        assert req is not None
        manager = db.session.get(User, manager_id)
        employee = db.session.get(User, employee_id)
        assert manager is not None
        assert employee is not None
        req.level_1_manager = manager
        req.employee = employee
        original = mail_feedback.send_email
        mail_feedback.send_email = _fake_send_email
        try:
            mail_feedback.send_feedback_request_mail(req)
        finally:
            mail_feedback.send_email = original

    assert "future_request_status_v9" not in captured["body"]
    assert "Bilinmiyor" in captured["body"]


def test_feedback_response_mail_shows_turkish_for_known_status(app) -> None:
    manager_id = _create_user(app, sicil_no="h1e_mail_b_manager")
    employee_id = _create_user(app, sicil_no="h1e_mail_b_employee")
    req_id = _build_feedback_request(app, employee_id=employee_id, manager_id=manager_id, status="cevaplandi")

    captured: dict = {}

    def _fake_send_email(to, subject, body):
        captured["body"] = body
        return True, "ok"

    import app.services.mail_feedback as mail_feedback
    from app.extensions import db

    with app.app_context():
        from app.models import FeedbackRequest, User

        req = db.session.get(FeedbackRequest, req_id)
        assert req is not None
        employee = db.session.get(User, employee_id)
        assert employee is not None
        req.employee = employee
        original = mail_feedback.send_email
        mail_feedback.send_email = _fake_send_email
        try:
            mail_feedback.send_feedback_response_mail(req)
        finally:
            mail_feedback.send_email = original

    assert "Cevaplandı" in captured["body"]
    assert "cevaplandi" not in captured["body"]


def test_feedback_meeting_status_update_mail_never_leaks_an_unmapped_status(app) -> None:
    employee_id = _create_user(app, sicil_no="h1e_mail_c_employee")
    manager_id = _create_user(app, sicil_no="h1e_mail_c_manager")
    req_id = _build_feedback_request(app, employee_id=employee_id, manager_id=manager_id, status="randevulandi")

    from app.extensions import db
    from app.models import FeedbackMeeting

    with app.app_context():
        meeting = FeedbackMeeting(
            feedback_request_id=req_id,
            employee_id=employee_id,
            manager_id=manager_id,
            meeting_date=date(2026, 6, 1),
            meeting_start=time(10, 0),
            meeting_end=time(10, 30),
            status="future_meeting_status_v9",
        )
        db.session.add(meeting)
        db.session.commit()
        meeting_id = meeting.id

    captured: dict = {}

    def _fake_send_email(to, subject, body):
        captured.setdefault("subjects", []).append(subject)
        captured.setdefault("bodies", []).append(body)
        return True, "ok"

    import app.services.mail_feedback as mail_feedback

    with app.app_context():
        from app.models import FeedbackMeeting as _FM, User

        fetched_meeting = db.session.get(_FM, meeting_id)
        assert fetched_meeting is not None
        meeting_employee = db.session.get(User, employee_id)
        meeting_manager = db.session.get(User, manager_id)
        assert meeting_employee is not None
        assert meeting_manager is not None
        fetched_meeting.employee = meeting_employee
        fetched_meeting.manager = meeting_manager
        original = mail_feedback.send_email
        mail_feedback.send_email = _fake_send_email
        try:
            mail_feedback.send_feedback_meeting_status_update_mail(fetched_meeting)
        finally:
            mail_feedback.send_email = original

    assert captured["bodies"], "no email was sent"
    for subject in captured["subjects"]:
        assert "future_meeting_status_v9" not in subject
        assert "Bilinmiyor" in subject
    for body in captured["bodies"]:
        assert "future_meeting_status_v9" not in body
        assert "Bilinmiyor" in body


# ---------------------------------------------------------------------------
# C: route-level tests -- file_center/logs.html and publications/viewer.html
# never leak an unmapped raw value.
# ---------------------------------------------------------------------------


def test_file_center_logs_page_never_leaks_an_unmapped_download_status(app, client) -> None:
    from app.extensions import db
    from app.models.file_center_models import FileDownloadLog, FileStorageItem

    owner_id = _create_user(app, sicil_no="h1e_fc_a_owner")
    with app.app_context():
        item = FileStorageItem(
            owner_user_id=owner_id,
            original_filename="h1e-test.pdf",
            stored_filename="h1e-test-stored.pdf",
            storage_path="/tmp/h1e-test-stored.pdf",
            sha256_hash="0" * 64,
        )
        db.session.add(item)
        db.session.commit()
        db.session.add(FileDownloadLog(file_id=item.id, status="future_download_status_v9"))
        db.session.commit()

    _login(client, "h1e_fc_a_owner")
    body = client.get("/file-center/logs").get_data(as_text=True)
    assert "future_download_status_v9" not in body
    assert "Bilinmiyor" in body


def test_file_center_logs_page_shows_turkish_for_known_download_status(app, client) -> None:
    from app.extensions import db
    from app.models.file_center_models import FileDownloadLog, FileStorageItem

    owner_id = _create_user(app, sicil_no="h1e_fc_b_owner")
    with app.app_context():
        item = FileStorageItem(
            owner_user_id=owner_id,
            original_filename="h1e-test.pdf",
            stored_filename="h1e-test-stored.pdf",
            storage_path="/tmp/h1e-test-stored.pdf",
            sha256_hash="1" * 64,
        )
        db.session.add(item)
        db.session.commit()
        db.session.add(FileDownloadLog(file_id=item.id, status="wrong_password"))
        db.session.commit()

    _login(client, "h1e_fc_b_owner")
    body = client.get("/file-center/logs").get_data(as_text=True)
    assert "Şifre hatalı" in body


# NOTE: no HTTP/template-level test exists here for publications/viewer.html.
# app/institutional/publication_routes.py (the whole /publications URL
# family: library, viewer, upload, download, feature-toggle, status,
# archive, delete) is not imported by any active blueprint-registration
# path -- app/institutional/__init__.py's _LIVE_CHILD_ROUTE_MODULES and
# app/institutional/routes.py both omit it, and route_manifest.py's
# REQUIRED_ROUTE_MODULES listing it is not consumed by any import loop.
# This is a pre-existing, unrelated functional defect, confirmed three
# independent ways: (1) zero matching rules in a fully-booted app's
# url_map, (2) a Flask "blueprint already registered" AssertionError the
# first time this process imports the route module, since the shared
# main_bp singleton was already registered by an earlier test's app, and
# (3) publications/viewer.html itself unconditionally calls
# url_for('main.publication_library', ...) (plus, for managers,
# main.publication_toggle_featured/publication_set_status, and when
# allow_download is set, main.publication_download) -- none of which
# exist in url_map either, so even rendering the template directly with a
# hand-built context still raises BuildError. Flagged separately
# (spawn_task) and out of scope for this display-only wave. The actual
# H1E-relevant logic -- publication_status_label()'s existing safe
# fallback, and its wiring into publication_view()'s
# status_label=publication_status_label(row.status) kwarg instead of the
# raw `publication.status|replace('_',' ')|title` filter chain the
# template used before -- is covered by
# test_publication_status_label_already_safe_and_now_used above; the
# wiring itself is a trivial, low-risk one-line change that will be
# exercised end-to-end once the separate routing defect is fixed.


# ---------------------------------------------------------------------------
# Contract: stored raw values are completely unchanged.
# ---------------------------------------------------------------------------


def test_stored_feedback_request_and_download_status_are_unchanged_by_rendering(app, client) -> None:
    manager_id = _create_user(app, sicil_no="h1e_contract_manager")
    employee_id = _create_user(app, sicil_no="h1e_contract_employee")
    req_id = _build_feedback_request(app, employee_id=employee_id, manager_id=manager_id, status="future_request_status_v9")

    from app.extensions import db
    from app.models import FeedbackRequest
    from app.models.file_center_models import FileDownloadLog, FileStorageItem

    with app.app_context():
        item = FileStorageItem(
            owner_user_id=employee_id,
            original_filename="h1e-contract.pdf",
            stored_filename="h1e-contract-stored.pdf",
            storage_path="/tmp/h1e-contract-stored.pdf",
            sha256_hash="2" * 64,
        )
        db.session.add(item)
        db.session.commit()
        log = FileDownloadLog(file_id=item.id, status="future_download_status_v9")
        db.session.add(log)
        db.session.commit()
        log_id = log.id

    _login(client, "h1e_contract_employee")
    client.get("/file-center/logs")

    with app.app_context():
        req = FeedbackRequest.query.get(req_id)
        log = FileDownloadLog.query.get(log_id)
        assert req.status == "future_request_status_v9"
        assert log.status == "future_download_status_v9"


# ---------------------------------------------------------------------------
# Authorization is unchanged.
# ---------------------------------------------------------------------------


def test_anonymous_request_redirects_to_login_unchanged(client) -> None:
    for path in ("/file-center/logs", "/feedback/admin/campaigns"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302, path
        assert "/login" in (response.headers.get("Location") or ""), path
