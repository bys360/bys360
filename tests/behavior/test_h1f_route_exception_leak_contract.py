"""BYS360 H1F -- route-layer exception-leak closure (agent 1 scope).

A prior phase (H1E) closed raw-status/enum-label leaks across the app. This
phase (H1F) targets a different class of defect: places where a REAL end
user could see a raw Python/technical exception message (str(exc), a
SQLAlchemy driver message, an exception class name, etc.) instead of a
safe, fixed Turkish message.

This agent's scope was: app/routes.py, app/routes_*.py, app/main_handlers/**,
app/admin/routes.py (route-handler files only, not services), and every
app/<domain>/routes.py or *_routes.py file except app/api/mobile/** and the
AI-decision-support families (owned by a parallel agent).

Across that scope, the dominant defect shape was:

    except Exception as exc:
        logger.exception(...)
        ...
        flash(f"<Turkish prefix>: {exc}", "danger")   # or flash(str(exc), ...)

which leaks whatever the underlying exception happened to be (a raw
SQLAlchemy driver message, an AttributeError/TypeError text, a Python
exception class name, an import error, ...) straight into a flash banner,
a JSON `message` field, or -- in one case -- a persisted audit-log row that
is later rendered verbatim to the file's own owner. All such call sites
were rewritten to show a fixed, safe Turkish message while preserving (or
adding, where missing) `logger.exception(...)` server-side logging.

NOTE ON `except ValueError as exc: flash(str(exc), ...)` and the
domain-specific `Communication*Error(RuntimeError)` / `UploadValidationError
(ValueError)` exception families: these are NOT exception leaks. They are
this codebase's established convention for surfacing intentional, hardcoded
Turkish business-validation messages from the service layer (verified by
grep: every `raise ValueError(...)` / `raise Communication*Error(...)` in
the call paths exercised here carries a literal Turkish string). They are
deliberately left untouched.

Every test below:
  (a) monkeypatches the specific function/method that a fixed route calls,
      making it raise a real exception carrying the sentinel string
      "TECHNICAL_SENTINEL_DO_NOT_SHOW_9F3A",
  (b) drives the real Flask route through the test client (or, for the
      audit-log case, through two real routes),
  (c) asserts the sentinel never reaches the HTTP response, the rendered
      HTML, or (for the file-center case) the persisted audit-log message
      a user can later read back,
  (d) asserts the new safe Turkish message IS present,
  (e) asserts the exception was actually logged server-side via caplog.

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB.
"""
from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1f_route_exception_leak_tmp" / "test_dbs"
_PASSWORD = "H1FRouteExceptionLeakTest1!"
_SENTINEL = "TECHNICAL_SENTINEL_DO_NOT_SHOW_9F3A"


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1f-route-exception-leak-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1f-route-exception-leak-first-login-test-pw")
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
    from app.services import runtime_schema

    with app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has

    return app


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


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
            ad="H1F",
            soyad="RouteExceptionLeakContract",
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


def _raise_sentinel(*_args, **_kwargs):
    raise Exception(_SENTINEL)  # noqa: TRY002 - deliberately generic, mirrors real unexpected-exception shape


# ---------------------------------------------------------------------------
# 1) app/file_center/routes.py -- file_center_download.
#    Standout finding: the raw exception used to be written into the
#    persisted FileAuditLog.message column via log_audit(..., message=f"...
#    {exc}"), which is later rendered verbatim by /file-center/logs
#    (templates/file_center/logs.html: `{{ row.message or '-' }}`) to the
#    file's own owner -- a real end user, not an ops-only surface.
# ---------------------------------------------------------------------------


def test_file_center_download_failure_never_leaks_raw_exception(app, client, caplog) -> None:
    from app.extensions import db
    from app.models.file_center_models import FileStorageItem

    user_id = _create_user(app, sicil_no="h1f_fc_download_user")
    with app.app_context():
        item = FileStorageItem(
            owner_user_id=user_id,
            original_filename="rapor.pdf",
            stored_filename="rapor_stored.pdf",
            storage_path="/tmp/does-not-matter.pdf",
            content_type="application/pdf",
            extension="pdf",
            size_bytes=1024,
            sha256_hash="0" * 64,
            status="active",
            scan_status="clean",
            is_deleted=False,
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    _login(client, "h1f_fc_download_user")

    import app.file_center.routes as fc_routes

    audit_calls: list[dict] = []
    real_log_audit = fc_routes.log_audit

    def _capturing_log_audit(action, **kwargs):
        audit_calls.append({"action": action, **kwargs})
        return real_log_audit(action, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fc_routes, "file_center_enabled", lambda: True)
        mp.setattr(fc_routes, "secure_file_path", _raise_sentinel)
        mp.setattr(fc_routes, "log_audit", _capturing_log_audit)

        with caplog.at_level(logging.ERROR, logger="app.file_center.routes"):
            resp = client.get(f"/file-center/download/{item_id}", follow_redirects=True)

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Dosya indirilemedi" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)

    # This is the standout finding: the audit-log `message` used to be
    # f"...: {exc}" -- a raw exception string -- and that column is later
    # rendered verbatim by /file-center/logs (templates/file_center/logs.html
    # `{{ row.message or '-' }}`) to the file's own owner, a real end user.
    download_failed_calls = [c for c in audit_calls if c["action"] == "file_download_failed"]
    assert download_failed_calls, "expected log_audit('file_download_failed', ...) to be called"
    for call in download_failed_calls:
        assert call.get("message") is not None
        assert _SENTINEL not in call["message"]
        assert "teknik bir hata oluştu" in call["message"]


# ---------------------------------------------------------------------------
# 2) app/file_center/routes.py -- chunk-upload JSON session creation.
#    The `message` field used to be str(exc); the chunk_upload.html inline
#    JS displays it verbatim via alert(err.message) / log(...).
# ---------------------------------------------------------------------------


def test_file_center_chunk_upload_session_create_json_never_leaks_raw_exception(app, client, caplog) -> None:
    user_id = _create_user(app, sicil_no="h1f_fc_chunk_user")
    _login(client, "h1f_fc_chunk_user")
    assert user_id

    import app.file_center.routes as fc_routes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fc_routes, "file_center_enabled", lambda: True)
        mp.setattr(fc_routes, "create_chunk_upload_session", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.file_center.routes"):
            resp = client.post(
                "/file-center/chunk-upload/session-json",
                data={
                    "total_size_bytes": "1000",
                    "chunk_size_bytes": "500",
                    "original_filename": "buyuk_dosya.zip",
                },
            )

    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["ok"] is False
    assert _SENTINEL not in payload["message"]
    assert payload["message"] == "Parçalı yükleme oturumu oluşturulamadı."
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# NOTE on app/institutional/publication_routes.py: this module is NOT
# imported/registered anywhere reachable in the live app. Its own family
# (app/institutional/__init__.py's `_LIVE_CHILD_ROUTE_MODULES`) explicitly
# does not list it ("Kapsam dışı eğitim/strateji/portal/repository route
# aileleri burada çağrılmaz" -- out-of-scope education/strategy/portal/
# repository route families are not called here), and the only other
# reference (app/institutional/route_manifest.py's REQUIRED_ROUTE_MODULES)
# is unused dead declarative data -- nothing imports/consumes it. Confirmed
# empirically: `app.url_map.iter_rules()` on a real `create_app()` contains
# zero "/publications*" rules. The five raw-exception-leak fixes made in
# that file (flash(f"...: {exc}", "danger") -> a fixed Turkish message) are
# harmless and correct should the module ever be wired back in, but since
# the route family is dead code today, no behavior test is added for it --
# see this agent's final report (DEAD_ORPHANED_PATH).


# ---------------------------------------------------------------------------
# 3) app/communication/feedback_routes.py -- feedback_pulse (POST).
# ---------------------------------------------------------------------------


def test_feedback_pulse_creation_never_leaks_raw_exception(app, client, caplog) -> None:
    _create_user(app, sicil_no="h1f_pulse_user")
    _login(client, "h1f_pulse_user")

    import app.communication.feedback_routes as feedback_routes
    import app.route_support as route_support_module

    with pytest.MonkeyPatch.context() as mp:
        # Menu-key gating is unrelated to this exception-leak fix; bypass it
        # deterministically instead of depending on live default menu config.
        mp.setattr(route_support_module, "can_access_menu", lambda user, key: True)
        mp.setattr(feedback_routes, "save_pulse_entry", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.communication.feedback_routes"):
            resp = client.post(
                "/feedback/pulse",
                data={"mood_value": "4", "short_note": "test"},
                follow_redirects=True,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Nabız kaydı oluşturulamadı" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 4) app/performance/admin_core_routes.py -- performance_criteria (create).
# ---------------------------------------------------------------------------


def test_performance_criteria_create_never_leaks_raw_exception(app, client, caplog) -> None:
    _create_user(app, sicil_no="h1f_criteria_admin")
    _login(client, "h1f_criteria_admin")

    from app.extensions import db

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(db.session, "add", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.performance.admin_core_routes"):
            resp = client.post(
                "/performance/criteria",
                data={"name": "Yeni Kriter", "description": "", "weight": "10", "sort_order": "1"},
                follow_redirects=True,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Kriter eklenirken hata oluştu" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 5) app/communication/announcement_popup_routes.py -- announcement_popup_toggle.
#    This one is caught by `except SQLAlchemyError`, not a bare `except
#    Exception` -- and had NO logger.exception at all before this fix.
# ---------------------------------------------------------------------------


def test_announcement_toggle_sqlalchemy_error_never_leaks_raw_exception(app, client, caplog) -> None:
    from app.extensions import db
    from app.models.announcement_popup_models import Announcement

    _create_user(app, sicil_no="h1f_announce_admin")
    with app.app_context():
        row = Announcement(title="H1F Test Duyuru", body="icerik", is_active=True)
        db.session.add(row)
        db.session.commit()
        announcement_id = row.id

    _login(client, "h1f_announce_admin")

    from sqlalchemy.exc import SQLAlchemyError

    import app.route_support as route_support_module

    def _raise_sqlalchemy_sentinel(*_args, **_kwargs):
        raise SQLAlchemyError(_SENTINEL)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(route_support_module, "can_access_menu", lambda user, key: True)
        mp.setattr(db.session, "commit", _raise_sqlalchemy_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.communication.announcement_popup_routes"):
            resp = client.post(f"/announcements/popup/{announcement_id}/toggle", follow_redirects=True)

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Duyuru durumu güncellenemedi" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 6) app/communication/daily_weather_mail_routes.py -- send-now.
# ---------------------------------------------------------------------------


def test_daily_weather_mail_send_now_never_leaks_raw_exception(app, client, caplog) -> None:
    _create_user(app, sicil_no="h1f_weather_admin")
    _login(client, "h1f_weather_admin")

    import app.communication.daily_weather_mail_routes as weather_routes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(weather_routes, "run_daily_weather_mail", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.communication.daily_weather_mail_routes"):
            resp = client.post("/executive-summary/daily-weather-mail/send-now", follow_redirects=True)

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Gönderim başlatılamadı" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 7) app/institutional/hr_personnel_operations_routes.py --
#    hr_self_service_request_delete. Representative of the ~70-occurrence
#    `logger.exception("Beklenmeyen hata: %s", exc); safe_db_rollback();
#    flash(str(exc), "danger")` -> generic safe message pattern repeated
#    across the HR institutional route files in this agent's scope.
# ---------------------------------------------------------------------------


def test_hr_self_service_request_delete_never_leaks_raw_exception(app, client, caplog) -> None:
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    user_id = _create_user(app, sicil_no="h1f_hr_selfservice_user", role="personel")
    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=user_id,
            request_type="bilgi_guncelleme",
            title="Test talebi",
            description="test",
            status="draft",
        )
        db.session.add(row)
        db.session.commit()
        request_id = row.id

    _login(client, "h1f_hr_selfservice_user")

    import app.institutional.hr_personnel_operations_routes as hr_ops_routes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(hr_ops_routes, "consume_form_token", lambda *a, **k: True)
        mp.setattr(db.session, "delete", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.institutional.hr_personnel_operations_routes"):
            resp = client.post(
                f"/hr-management/self-service/requests/{request_id}/delete",
                data={"form_token": "irrelevant-because-patched"},
                follow_redirects=True,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "İşlem sırasında beklenmeyen bir hata oluştu" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 8) app/communication/surveys_routes.py -- survey_bulk_action. Covers the
#    f-string-with-suffix leak pattern (`flash(f"...: {exc}", "danger")`)
#    for the communication/surveys family.
# ---------------------------------------------------------------------------


def test_survey_bulk_action_never_leaks_raw_exception(app, client, caplog) -> None:
    from app.extensions import db
    from app.models import Survey

    admin_id = _create_user(app, sicil_no="h1f_survey_admin")
    with app.app_context():
        survey = Survey(
            title="H1F Test Anketi",
            survey_type="kurum_ici",
            status="draft",
            created_by_user_id=admin_id,
        )
        db.session.add(survey)
        db.session.commit()
        survey_id = survey.id

    _login(client, "h1f_survey_admin")

    import app.communication.surveys_routes as surveys_routes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(surveys_routes, "_survey_manager_allowed", lambda: True)
        mp.setattr(surveys_routes, "_service_bulk_survey_action", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.communication.surveys_routes"):
            resp = client.post(
                "/survey-bulk-action",
                data={"survey_ids": [str(survey_id)], "bulk_action": "archive", "current_status": "draft"},
                follow_redirects=True,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Toplu anket işlemi sırasında hata oluştu" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 9) app/communication/messages_routes.py -- messages_new_impl (POST).
#    Coordinator finding: this agent's own diff added `| exc=%s` to the
#    logger.exception() call at this site but left the flash() itself
#    unchanged -- flash(f"Mesaj gonderilirken hata olustu: {exc}", "danger")
#    -- a sibling of the already-fixed messages_send_impl leak a few
#    hundred lines below in the same file. Found and fixed during the
#    coordinator's residual re-scan of this agent's diff.
# ---------------------------------------------------------------------------


def test_messages_new_creation_never_leaks_raw_exception(app, client, caplog) -> None:
    _create_user(app, sicil_no="h1f_msg_new_sender")
    recipient_id = _create_user(app, sicil_no="h1f_msg_new_recipient")
    _login(client, "h1f_msg_new_sender")

    import app.communication.messages_routes as messages_routes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(messages_routes, "consume_form_token", lambda *a, **k: True)
        mp.setattr(messages_routes, "_svc_create_direct_message_with_attachments", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.communication.messages_routes"):
            resp = client.post(
                "/messages/new",
                data={"recipient_user_id": str(recipient_id), "body": "merhaba"},
                follow_redirects=True,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Mesaj gönderilirken hata oluştu" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 10) app/institutional/hr_personnel_operations_routes.py -- bulk document
#     upload's per-file except block. Coordinator finding: `except Exception
#     as exc: skipped.append(str(exc))` could store a raw, unexpected
#     exception's text (not just the function's own hardcoded ValueError
#     messages) into PersonnelDocumentUploadBatch.note, a persisted DB
#     column. No current template renders that specific column, so this
#     was not an active leak today -- but it is one accidental future query
#     away from becoming one, so it was hardened defensively: only a
#     ValueError's (always hardcoded, safe) text is stored verbatim; any
#     other exception is replaced with a fixed safe message and logged.
# ---------------------------------------------------------------------------


def test_hr_bulk_document_upload_unexpected_error_never_leaks_raw_exception(app, client, caplog) -> None:
    from io import BytesIO

    target_user_id = _create_user(app, sicil_no="h1f_hr_bulk_target", role="personel")
    _create_user(app, sicil_no="h1f_hr_bulk_manager", role="admin")
    _login(client, "h1f_hr_bulk_manager")

    import app.institutional.hr_personnel_operations_routes as hr_routes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(hr_routes, "consume_form_token", lambda *a, **k: True)
        mp.setattr(hr_routes, "_save_file", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.institutional.hr_personnel_operations_routes"):
            resp = client.post(
                "/hr-management/personnel-operations/document/bulk-upload",
                data={
                    "user_id": str(target_user_id),
                    "document_files": (BytesIO(b"test-bytes"), "belge.pdf"),
                },
                content_type="multipart/form-data",
                follow_redirects=True,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)

    from app.models.hr_models import PersonnelDocumentUploadBatch

    with app.app_context():
        batches = PersonnelDocumentUploadBatch.query.filter_by(user_id=target_user_id).all()
        for batch in batches:
            assert batch.note is None or _SENTINEL not in batch.note


# ---------------------------------------------------------------------------
# 11) app/performance/performance_archive_routes.py -- performance_archive_import.
#     Coordinator finding: flagged by another agent as belonging to this
#     agent's scope (a route file) but not present in this agent's diff --
#     confirmed still leaking, fixed during the coordinator's cross-agent
#     boundary check.
# ---------------------------------------------------------------------------


def test_performance_archive_import_never_leaks_raw_exception(app, client, caplog) -> None:
    from io import BytesIO

    _create_user(app, sicil_no="h1f_archive_admin", role="admin")
    _login(client, "h1f_archive_admin")

    import app.performance.performance_archive_routes as archive_routes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(archive_routes, "import_archive_results_from_excel", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.performance.performance_archive_routes"):
            resp = client.post(
                "/performance/archive/import",
                data={"archive_excel": (BytesIO(b"not-a-real-xlsx"), "arsiv.xlsx")},
                content_type="multipart/form-data",
                follow_redirects=True,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Excel aktarımı yapılamadı" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 12) app/performance/v2_1_3_personnel_category_card_routes.py --
#     performance_v2_1_3_personnel_category_card (assign_user_category action).
#     Same cross-agent boundary gap as finding 11.
# ---------------------------------------------------------------------------


def test_v2_1_3_personnel_category_assign_never_leaks_raw_exception(app, client, caplog) -> None:
    target_user_id = _create_user(app, sicil_no="h1f_v213_target", role="personel")
    _create_user(app, sicil_no="h1f_v213_admin", role="admin")
    _login(client, "h1f_v213_admin")

    import app.performance.v2_1_3_personnel_category_card_routes as v213_routes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(v213_routes, "assign_personnel_category_from_card", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.performance.v2_1_3_personnel_category_card_routes"):
            resp = client.post(
                "/performance/v2-1-3-personnel-category-card",
                data={"action": "assign_user_category", "user_id": str(target_user_id), "category_key": "diger"},
                follow_redirects=True,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Kategori işlemi tamamlanamadı" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)
