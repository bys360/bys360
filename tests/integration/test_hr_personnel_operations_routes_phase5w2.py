"""BYS360 Phase 5 coverage wave 2 (Agent 3) -- HR personnel self-service +
personnel-operations routes.

Target: ``app/institutional/hr_personnel_operations_routes.py``. Real Flask
``test_client()`` against the real routes (blueprint ``main_bp``), a real
per-test SQLite DB, real ``User``/``PersonnelSelfServiceRequest``/
``PersonnelDocument``/``PersonnelProcessNote``/``PersonnelStatusHistory``/
``PersonnelPositionHistory`` ORM rows, real login via ``POST /login``, and
real multipart file uploads written to an isolated temp upload directory
(never the repo tree).

Test-infra note (DB engine choice): this module deliberately uses a
per-test **file-backed** SQLite database (``sqlite:///<tmp file>``, matching
the pattern already established in
``tests/security/test_account_change_photo_redirect_guard.py``) instead of
``sqlite:///:memory:``. This target module calls ``_table_exists()``
(``app/institutional/hr_personnel_operations_routes.py``), which opens a
*second* raw connection via ``sqlalchemy.inspect(db.engine)`` in the middle
of an already-open write transaction (see ``_write_request_log`` and
``_template_by_id``/``_template_rows``, which call it while a
``PersonnelSelfServiceRequest`` insert is pending). Empirically, with a
``:memory:`` engine this second connection checkout/checkin causes SQLite's
Python driver to roll back the *shared* physical connection used by
``SingletonThreadPool`` when the inspector's logical connection is closed,
silently discarding the still-uncommitted row and turning the route's own
final ``db.session.commit()`` into a spurious
``sqlalchemy.orm.exc.StaleDataError`` ("expected to update 1 row(s); 0 were
matched"). This reproduces even via a **direct**, route-free ORM sequence
(add + flush + ``inspect(db.engine).get_table_names()`` + mutate + commit)
against a bare ``:memory:`` engine, and disappears completely when the same
sequence runs against a file-backed engine -- so it is a SQLite
``:memory:``/connection-pool test artifact, not app behavior; production
runs against a real database file/server where independent connections do
not share transaction state. Using a file-backed per-test DB (unique
``uuid4`` filename, deleted only by OS temp cleanup) keeps every test
isolated while sidestepping the artifact.
"""
from __future__ import annotations

import io
import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360_pytest_tmp_agent3" / "hr_ops_phase5w2" / "dbs"
_TEST_UPLOAD_ROOT = Path(tempfile.gettempdir()) / "bys360_pytest_tmp_agent3" / "hr_ops_phase5w2" / "uploads"

DEFAULT_PASSWORD = "Phase5w2HrOps1!"


def _make_app(monkeypatch, **config_overrides):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"
    upload_dir = _TEST_UPLOAD_ROOT / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-hr-personnel-operations-phase5w2")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
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

    # BYS360_P13B_CONFIG_ISOLATION-style: app.config değişikliği db.init_app
    # sonrasında yapılırsa SQLAlchemy motorunu değiştirmez. Test DB ayarını
    # create_app() öncesinde doğrudan Config sınıfına uygula.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    # B2-F06: new HR documents go to PRIVATE_UPLOAD_FOLDER (outside the static folder), not
    # UPLOAD_FOLDER; both roots stay inside this test's own temp upload directory.
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        UPLOAD_FOLDER=str(upload_dir),
        PRIVATE_UPLOAD_FOLDER=str(upload_dir / "private"),
    )
    app.config.update(config_overrides)

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _create_user(
    app,
    *,
    sicil_no,
    email,
    role="personel",
    birim=None,
    yonetici_sicil=None,
    password=DEFAULT_PASSWORD,
):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=email,
            ad="Wave2",
            soyad="HrOps",
            role=role,
            birim=birim,
            yonetici_sicil=yonetici_sicil,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=DEFAULT_PASSWORD):
    resp = client.post(
        "/login",
        data={"sicil_or_email": sicil_no, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" not in resp.headers.get("Location", "")
    return resp


def _set_token(client, namespace, scope, token=None):
    token = token or uuid.uuid4().hex
    with client.session_transaction() as sess:
        sess[f"form_token:{namespace}:{scope}"] = token
    return token


def _pdf(name="belge.pdf", content=b"%PDF-1.4 fake content"):
    return (io.BytesIO(content), name)


def _exe(name="malware.exe", content=b"MZ fake binary"):
    return (io.BytesIO(content), name)


def _self_service_request_count(app) -> int:
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        return db.session.query(PersonnelSelfServiceRequest).count()


def _document_count(app) -> int:
    from app.extensions import db
    from app.models import PersonnelDocument

    with app.app_context():
        return db.session.query(PersonnelDocument).count()


# ===========================================================================
# 1) SELF-SERVICE REQUESTS (own scope, login_required only)
# ===========================================================================


def test_self_service_requests_page_loads_for_authenticated_user(app, client):
    _create_user(app, sicil_no="w2p001", email="w2p001@bys360.test", role="personel")
    _login(client, "w2p001")

    resp = client.get("/hr-management/self-service/requests")

    assert resp.status_code == 200
    assert "hr_self_service_requests" not in resp.get_data(as_text=True)  # template renders real content, not a raw error stub


def test_self_service_request_save_draft_creates_row_with_draft_status(app, client):
    _create_user(app, sicil_no="w2p002", email="w2p002@bys360.test", role="personel")
    _login(client, "w2p002")
    token = _set_token(client, "hr_self_service_request_save", "hr_self_service_requests")

    resp = client.post(
        "/hr-management/self-service/requests/save",
        data={
            "form_token": token,
            "title": "Bilgi güncelleme talebim",
            "description": "Adres bilgimi güncellemek istiyorum.",
            "action_mode": "draft",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert "request_id=" in resp.headers.get("Location", "")

    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = db.session.query(PersonnelSelfServiceRequest).one()
        assert row.status == "draft"
        assert row.submitted_at is None
        assert row.title == "Bilgi güncelleme talebim"


def test_self_service_request_save_submit_sets_submitted_status_and_due_at(app, client):
    _create_user(app, sicil_no="w2p003", email="w2p003@bys360.test", role="personel")
    _login(client, "w2p003")
    token = _set_token(client, "hr_self_service_request_save", "hr_self_service_requests")

    resp = client.post(
        "/hr-management/self-service/requests/save",
        data={
            "form_token": token,
            "title": "İzin talebim",
            "description": "Yıllık izin talebi açıklaması.",
            "desired_completion_date": "2026-09-01",
            "action_mode": "submit",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302

    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = db.session.query(PersonnelSelfServiceRequest).one()
        assert row.status == "submitted"
        assert row.submitted_at is not None
        assert row.due_at is not None


def test_self_service_request_save_with_attachment_persists_real_file(app, client):
    _create_user(app, sicil_no="w2p004", email="w2p004@bys360.test", role="personel")
    _login(client, "w2p004")
    token = _set_token(client, "hr_self_service_request_save", "hr_self_service_requests")

    resp = client.post(
        "/hr-management/self-service/requests/save",
        data={
            "form_token": token,
            "title": "Belge talebim",
            "description": "Hizmet belgesi istiyorum.",
            "action_mode": "submit",
            "request_files": _pdf(),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302

    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequestAttachment

    with app.app_context():
        attachment = db.session.query(PersonnelSelfServiceRequestAttachment).one()
        assert attachment.original_filename == "belge.pdf"
        assert os.path.exists(attachment.storage_path)
        assert str(_TEST_UPLOAD_ROOT) in attachment.storage_path
        private_dir = Path(app.config["PRIVATE_UPLOAD_FOLDER"]) / "hr" / "personnel_documents"
        assert Path(attachment.storage_path).parent == private_dir


def test_self_service_request_save_missing_title_rejected_no_row_created(app, client):
    _create_user(app, sicil_no="w2p005", email="w2p005@bys360.test", role="personel")
    _login(client, "w2p005")
    token = _set_token(client, "hr_self_service_request_save", "hr_self_service_requests")

    resp = client.post(
        "/hr-management/self-service/requests/save",
        data={"form_token": token, "title": "", "description": "açıklama var ama başlık yok", "action_mode": "draft"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _self_service_request_count(app) == 0


def test_self_service_request_save_completion_date_before_effective_date_rejected(app, client):
    _create_user(app, sicil_no="w2p006", email="w2p006@bys360.test", role="personel")
    _login(client, "w2p006")
    token = _set_token(client, "hr_self_service_request_save", "hr_self_service_requests")

    resp = client.post(
        "/hr-management/self-service/requests/save",
        data={
            "form_token": token,
            "title": "Tarih hatalı talep",
            "description": "Tarih sırası hatalı test",
            "requested_effective_date": "2026-09-10",
            "desired_completion_date": "2026-09-01",
            "action_mode": "draft",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _self_service_request_count(app) == 0


def test_self_service_request_save_invalid_form_token_rejected_no_row_created(app, client):
    _create_user(app, sicil_no="w2p007", email="w2p007@bys360.test", role="personel")
    _login(client, "w2p007")
    _set_token(client, "hr_self_service_request_save", "hr_self_service_requests", token="expected-token")

    resp = client.post(
        "/hr-management/self-service/requests/save",
        data={"form_token": "wrong-token", "title": "t", "description": "d", "action_mode": "draft"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _self_service_request_count(app) == 0


def test_self_service_request_save_disallowed_extension_rejected_no_row_created(app, client):
    _create_user(app, sicil_no="w2p008", email="w2p008@bys360.test", role="personel")
    _login(client, "w2p008")
    token = _set_token(client, "hr_self_service_request_save", "hr_self_service_requests")

    resp = client.post(
        "/hr-management/self-service/requests/save",
        data={
            "form_token": token,
            "title": "Zararlı dosya talebi",
            "description": "Yalnızca izinli uzantılar kabul edilmeli",
            "action_mode": "draft",
            "request_files": _exe(),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    # Whole save is rolled back -- no partial persistence even though the
    # text fields were valid.
    assert _self_service_request_count(app) == 0

    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequestAttachment

    with app.app_context():
        assert db.session.query(PersonnelSelfServiceRequestAttachment).count() == 0


def test_self_service_request_edit_of_submitted_status_blocked(app, client):
    uid = _create_user(app, sicil_no="w2p009", email="w2p009@bys360.test", role="personel")

    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=uid, created_by_id=uid, title="Zaten gönderildi", description="d",
            request_type="bilgi_guncelleme", priority="normal", status="submitted", submitted_at=utc_now(),
        )
        db.session.add(row)
        db.session.commit()
        req_id = row.id

    _login(client, "w2p009")
    token = _set_token(client, "hr_self_service_request_save", "hr_self_service_requests")

    resp = client.post(
        "/hr-management/self-service/requests/save",
        data={
            "form_token": token,
            "request_id": str(req_id),
            "title": "Değiştirilmeye çalışıldı",
            "description": "d2",
            "action_mode": "draft",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        reloaded_row = db.session.get(PersonnelSelfServiceRequest, req_id)
        assert reloaded_row is not None
        assert reloaded_row.title == "Zaten gönderildi"
        assert reloaded_row.status == "submitted"


def test_self_service_request_delete_removes_draft_row(app, client):
    uid = _create_user(app, sicil_no="w2p010", email="w2p010@bys360.test", role="personel")

    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=uid, created_by_id=uid, title="Silinecek taslak", description="d",
            request_type="bilgi_guncelleme", priority="normal", status="draft",
        )
        db.session.add(row)
        db.session.commit()
        req_id = row.id

    _login(client, "w2p010")
    token = _set_token(client, "hr_self_service_request_delete", "hr_self_service_requests")

    resp = client.post(
        f"/hr-management/self-service/requests/{req_id}/delete",
        data={"form_token": token},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _self_service_request_count(app) == 0


def test_self_service_request_delete_blocks_non_draft_status(app, client):
    uid = _create_user(app, sicil_no="w2p011", email="w2p011@bys360.test", role="personel")

    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=uid, created_by_id=uid, title="Onaylı talep", description="d",
            request_type="bilgi_guncelleme", priority="normal", status="approved", submitted_at=utc_now(),
        )
        db.session.add(row)
        db.session.commit()
        req_id = row.id

    _login(client, "w2p011")
    token = _set_token(client, "hr_self_service_request_delete", "hr_self_service_requests")

    resp = client.post(
        f"/hr-management/self-service/requests/{req_id}/delete",
        data={"form_token": token},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _self_service_request_count(app) == 1


def test_self_service_attachment_download_denied_for_other_users_request(app):
    _create_user(app, sicil_no="w2p012", email="w2p012@bys360.test", role="personel")
    _create_user(app, sicil_no="w2p013", email="w2p013@bys360.test", role="personel")

    owner_client = app.test_client()
    _login(owner_client, "w2p012")
    token = _set_token(owner_client, "hr_self_service_request_save", "hr_self_service_requests")
    owner_client.post(
        "/hr-management/self-service/requests/save",
        data={
            "form_token": token,
            "title": "Sahibinin talebi",
            "description": "d",
            "action_mode": "draft",
            "request_files": _pdf(),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    from app.extensions import db
    from app.models.hr_models import (
        PersonnelSelfServiceRequest,
        PersonnelSelfServiceRequestAttachment,
    )

    with app.app_context():
        req_row = db.session.query(PersonnelSelfServiceRequest).one()
        att_row = db.session.query(PersonnelSelfServiceRequestAttachment).one()
        req_id, att_id = req_row.id, att_row.id
        stored_path = att_row.storage_path

    intruder_client = app.test_client()
    _login(intruder_client, "w2p013")

    resp = intruder_client.get(
        f"/hr-management/self-service/request/{req_id}/attachment/{att_id}/download",
        follow_redirects=False,
    )

    # Ownership boundary: the route must NOT stream another user's file.
    assert resp.status_code == 302
    assert resp.content_type != "application/octet-stream"
    assert os.path.exists(stored_path)  # file itself untouched


# ===========================================================================
# 2) MANAGER REVIEW INDEX + REVIEW ACTION (manager_required + menu_key_required)
# ===========================================================================


def test_personnel_request_review_index_loads_for_manager(app, client):
    _create_user(app, sicil_no="w2m001", email="w2m001@bys360.test", role="admin")
    _login(client, "w2m001")

    resp = client.get("/hr-management/personnel-operations/requests")

    assert resp.status_code == 200


def test_personnel_request_review_index_denied_for_non_manager(app, client):
    _create_user(app, sicil_no="w2m002", email="w2m002@bys360.test", role="personel")
    _login(client, "w2m002")

    resp = client.get("/hr-management/personnel-operations/requests")

    assert resp.status_code == 403


def test_personnel_request_review_index_denied_when_unauthenticated(app, client):
    resp = client.get("/hr-management/personnel-operations/requests", follow_redirects=False)

    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")


def test_personnel_request_review_approve_transitions_status_and_sets_handler(app, client):
    mgr_id = _create_user(app, sicil_no="w2m003", email="w2m003@bys360.test", role="admin")
    emp_id = _create_user(app, sicil_no="w2e003", email="w2e003@bys360.test", role="personel")

    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=emp_id, created_by_id=emp_id, title="Onay bekleyen talep", description="d",
            request_type="belge_talebi", priority="normal", status="submitted", submitted_at=utc_now(),
        )
        db.session.add(row)
        db.session.commit()
        req_id = row.id

    _login(client, "w2m003")
    token = _set_token(client, "hr_personnel_request_review", "hr_personnel_operations")

    resp = client.post(
        f"/hr-management/personnel-operations/request/{req_id}/review",
        data={"form_token": token, "review_action": "approve", "decision_note": "Uygun görüldü"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        updated = db.session.get(PersonnelSelfServiceRequest, req_id)
        assert updated is not None
        assert updated.status == "approved"
        assert updated.current_handler_id == mgr_id
        assert updated.decision_note == "Uygun görüldü"
        assert updated.closed_at is not None
        assert updated.first_response_at is not None


def test_personnel_request_review_reject_sets_closed_at(app, client):
    _create_user(app, sicil_no="w2m004", email="w2m004@bys360.test", role="admin")
    emp_id = _create_user(app, sicil_no="w2e004", email="w2e004@bys360.test", role="personel")

    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=emp_id, created_by_id=emp_id, title="Reddedilecek talep", description="d",
            request_type="belge_talebi", priority="normal", status="submitted", submitted_at=utc_now(),
        )
        db.session.add(row)
        db.session.commit()
        req_id = row.id

    _login(client, "w2m004")
    token = _set_token(client, "hr_personnel_request_review", "hr_personnel_operations")

    resp = client.post(
        f"/hr-management/personnel-operations/request/{req_id}/review",
        data={"form_token": token, "review_action": "reject", "decision_note": "Uygun değil"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        updated = db.session.get(PersonnelSelfServiceRequest, req_id)
        assert updated is not None
        assert updated.status == "rejected"
        assert updated.closed_at is not None


def test_personnel_request_review_return_reopens_for_employee_editing(app, client):
    _create_user(app, sicil_no="w2m005", email="w2m005@bys360.test", role="admin")
    emp_id = _create_user(app, sicil_no="w2e005", email="w2e005@bys360.test", role="personel")

    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=emp_id, created_by_id=emp_id, title="Eksik bilgi var", description="d",
            request_type="belge_talebi", priority="normal", status="submitted", submitted_at=utc_now(),
        )
        db.session.add(row)
        db.session.commit()
        req_id = row.id

    _login(client, "w2m005")
    token = _set_token(client, "hr_personnel_request_review", "hr_personnel_operations")

    resp = client.post(
        f"/hr-management/personnel-operations/request/{req_id}/review",
        data={"form_token": token, "review_action": "return", "decision_note": "Ek belge gerekli"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        updated = db.session.get(PersonnelSelfServiceRequest, req_id)
        assert updated is not None
        assert updated.status == "returned"
        # "returned" is still an editable state for the employee.
        assert updated.status in {"draft", "returned"}


def test_personnel_request_review_invalid_action_rejected_status_unchanged(app, client):
    _create_user(app, sicil_no="w2m006", email="w2m006@bys360.test", role="admin")
    emp_id = _create_user(app, sicil_no="w2e006", email="w2e006@bys360.test", role="personel")

    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=emp_id, created_by_id=emp_id, title="Bilinmeyen aksiyon testi", description="d",
            request_type="belge_talebi", priority="normal", status="submitted", submitted_at=utc_now(),
        )
        db.session.add(row)
        db.session.commit()
        req_id = row.id

    _login(client, "w2m006")
    token = _set_token(client, "hr_personnel_request_review", "hr_personnel_operations")

    resp = client.post(
        f"/hr-management/personnel-operations/request/{req_id}/review",
        data={"form_token": token, "review_action": "self_destruct", "decision_note": "x"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        updated = db.session.get(PersonnelSelfServiceRequest, req_id)
        assert updated is not None
        assert updated.status == "submitted"
        assert updated.decision_note is None


def test_personnel_request_review_invalid_form_token_rejected_status_unchanged(app, client):
    _create_user(app, sicil_no="w2m007", email="w2m007@bys360.test", role="admin")
    emp_id = _create_user(app, sicil_no="w2e007", email="w2e007@bys360.test", role="personel")

    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=emp_id, created_by_id=emp_id, title="Yanlış token testi", description="d",
            request_type="belge_talebi", priority="normal", status="submitted", submitted_at=utc_now(),
        )
        db.session.add(row)
        db.session.commit()
        req_id = row.id

    _login(client, "w2m007")
    _set_token(client, "hr_personnel_request_review", "hr_personnel_operations", token="expected")

    resp = client.post(
        f"/hr-management/personnel-operations/request/{req_id}/review",
        data={"form_token": "wrong", "review_action": "approve"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        updated = db.session.get(PersonnelSelfServiceRequest, req_id)
        assert updated is not None
        assert updated.status == "submitted"


def test_personnel_request_review_wrong_scope_denied_status_unchanged(app):
    """A birim_sorumlusu manager scoped to unit "IK" cannot approve/reject a
    request that belongs to an employee in a different, unrelated unit
    ("Finans"). ``_request_in_scope`` must reject it (caught ValueError ->
    flash + redirect), leaving the request's status untouched."""
    _create_user(app, sicil_no="w2mgrA", email="w2mgrA@bys360.test", role="birim_sorumlusu", birim="IK")
    emp_b = _create_user(app, sicil_no="w2empB", email="w2empB@bys360.test", role="personel", birim="Finans")

    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=emp_b, created_by_id=emp_b, title="Kapsam dışı talep", description="d",
            request_type="belge_talebi", priority="normal", status="submitted", submitted_at=utc_now(),
        )
        db.session.add(row)
        db.session.commit()
        req_id = row.id

    mgr_client = app.test_client()
    _login(mgr_client, "w2mgrA")
    token = _set_token(mgr_client, "hr_personnel_request_review", "hr_personnel_operations")

    resp = mgr_client.post(
        f"/hr-management/personnel-operations/request/{req_id}/review",
        data={"form_token": token, "review_action": "approve", "decision_note": "x"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        updated = db.session.get(PersonnelSelfServiceRequest, req_id)
        assert updated is not None
        assert updated.status == "submitted"
        assert updated.decision_note is None
        assert updated.current_handler_id is None


# ===========================================================================
# 3) PERSONNEL DOCUMENTS (manager_required + menu_key_required, scope-gated)
# ===========================================================================


def test_document_save_creates_new_document_with_valid_pdf_upload(app, client):
    emp_id = _create_user(app, sicil_no="w2d001", email="w2d001@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgr001", email="w2mgr001@bys360.test", role="admin")
    _login(client, "w2mgr001")
    token = _set_token(client, "hr_personnel_document_save", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/document/save",
        data={
            "form_token": token,
            "user_id": str(emp_id),
            "category": "ozluk",
            "title": "Kimlik Fotokopisi",
            "document_file": _pdf(),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    from app.extensions import db
    from app.models import PersonnelDocument

    with app.app_context():
        doc = db.session.query(PersonnelDocument).one()
        assert doc.title == "Kimlik Fotokopisi"
        assert doc.user_id == emp_id
        assert os.path.exists(doc.storage_path)


def test_document_save_rejects_disallowed_extension_no_row_created(app, client):
    emp_id = _create_user(app, sicil_no="w2d002", email="w2d002@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgr002", email="w2mgr002@bys360.test", role="admin")
    _login(client, "w2mgr002")
    token = _set_token(client, "hr_personnel_document_save", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/document/save",
        data={
            "form_token": token,
            "user_id": str(emp_id),
            "category": "ozluk",
            "title": "Zararlı dosya",
            "document_file": _exe(),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _document_count(app) == 0


def test_document_save_new_document_without_file_rejected(app, client):
    emp_id = _create_user(app, sicil_no="w2d003", email="w2d003@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgr003", email="w2mgr003@bys360.test", role="admin")
    _login(client, "w2mgr003")
    token = _set_token(client, "hr_personnel_document_save", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/document/save",
        data={"form_token": token, "user_id": str(emp_id), "category": "ozluk", "title": "Dosyasız belge"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _document_count(app) == 0


def test_document_save_update_replaces_file_and_removes_old_file(app, client):
    emp_id = _create_user(app, sicil_no="w2d004", email="w2d004@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgr004", email="w2mgr004@bys360.test", role="admin")
    _login(client, "w2mgr004")

    token1 = _set_token(client, "hr_personnel_document_save", "hr_personnel_operations")
    client.post(
        "/hr-management/personnel-operations/document/save",
        data={
            "form_token": token1,
            "user_id": str(emp_id),
            "category": "ozluk",
            "title": "İlk sürüm",
            "document_file": _pdf("ilk.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    from app.extensions import db
    from app.models import PersonnelDocument

    with app.app_context():
        doc = db.session.query(PersonnelDocument).one()
        doc_id = doc.id
        old_path = doc.storage_path
    assert os.path.exists(old_path)

    token2 = _set_token(client, "hr_personnel_document_save", "hr_personnel_operations")
    resp = client.post(
        "/hr-management/personnel-operations/document/save",
        data={
            "form_token": token2,
            "user_id": str(emp_id),
            "document_id": str(doc_id),
            "category": "ozluk",
            "title": "Güncellenmiş sürüm",
            "document_file": _pdf("guncel.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        reloaded_doc = db.session.get(PersonnelDocument, doc_id)
        assert reloaded_doc is not None
        assert reloaded_doc.title == "Güncellenmiş sürüm"
        assert reloaded_doc.original_filename == "guncel.pdf"
        new_path = reloaded_doc.storage_path
    assert os.path.exists(new_path)
    assert new_path != old_path
    assert not os.path.exists(old_path)  # old file cleaned up


def test_document_delete_removes_row_and_file(app, client):
    emp_id = _create_user(app, sicil_no="w2d005", email="w2d005@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgr005", email="w2mgr005@bys360.test", role="admin")
    _login(client, "w2mgr005")

    token1 = _set_token(client, "hr_personnel_document_save", "hr_personnel_operations")
    client.post(
        "/hr-management/personnel-operations/document/save",
        data={
            "form_token": token1,
            "user_id": str(emp_id),
            "category": "ozluk",
            "title": "Silinecek belge",
            "document_file": _pdf(),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    from app.extensions import db
    from app.models import PersonnelDocument

    with app.app_context():
        doc = db.session.query(PersonnelDocument).one()
        doc_id = doc.id
        stored_path = doc.storage_path
    assert os.path.exists(stored_path)

    token2 = _set_token(client, "hr_personnel_document_delete", "hr_personnel_operations")
    resp = client.post(
        f"/hr-management/personnel-operations/document/{doc_id}/delete",
        data={"form_token": token2, "user_id": str(emp_id)},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _document_count(app) == 0
    assert not os.path.exists(stored_path)


def test_document_download_denied_for_out_of_scope_document(app):
    _create_user(app, sicil_no="w2mgrB", email="w2mgrB@bys360.test", role="birim_sorumlusu", birim="IK")
    emp_ik = _create_user(app, sicil_no="w2empIK", email="w2empIK@bys360.test", role="personel", birim="IK")
    _create_user(app, sicil_no="w2mgrC", email="w2mgrC@bys360.test", role="birim_sorumlusu", birim="Finans")

    ik_client = app.test_client()
    _login(ik_client, "w2mgrB")
    token = _set_token(ik_client, "hr_personnel_document_save", "hr_personnel_operations")
    ik_client.post(
        "/hr-management/personnel-operations/document/save",
        data={
            "form_token": token,
            "user_id": str(emp_ik),
            "category": "ozluk",
            "title": "IK biriminin belgesi",
            "document_file": _pdf(),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    from app.extensions import db
    from app.models import PersonnelDocument

    with app.app_context():
        doc = db.session.query(PersonnelDocument).one()
        doc_id = doc.id
        stored_path = doc.storage_path

    finans_client = app.test_client()
    _login(finans_client, "w2mgrC")
    resp = finans_client.get(
        f"/hr-management/personnel-operations/document/{doc_id}/download",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.content_type != "application/octet-stream"
    assert os.path.exists(stored_path)  # denial did not touch the file


def test_document_bulk_upload_partial_success_creates_batch_with_kismi_status(app, client):
    emp_id = _create_user(app, sicil_no="w2d006", email="w2d006@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgr006", email="w2mgr006@bys360.test", role="admin")
    _login(client, "w2mgr006")
    token = _set_token(client, "hr_personnel_document_bulk_upload", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/document/bulk-upload",
        data={
            "form_token": token,
            "user_id": str(emp_id),
            "category": "ozluk",
            "document_files": [_pdf("gecerli.pdf"), _exe("virus.exe")],
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _document_count(app) == 1

    from app.extensions import db
    from app.models import PersonnelDocumentUploadBatch

    with app.app_context():
        batch = db.session.query(PersonnelDocumentUploadBatch).one()
        assert batch.success_count == 1
        assert batch.total_file_count == 2
        assert batch.status == "kismi"


def test_document_bulk_upload_all_invalid_rejected_no_rows_no_batch(app, client):
    emp_id = _create_user(app, sicil_no="w2d007", email="w2d007@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgr007", email="w2mgr007@bys360.test", role="admin")
    _login(client, "w2mgr007")
    token = _set_token(client, "hr_personnel_document_bulk_upload", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/document/bulk-upload",
        data={
            "form_token": token,
            "user_id": str(emp_id),
            "category": "ozluk",
            "document_files": [_exe("v1.exe"), _exe("v2.exe")],
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _document_count(app) == 0

    from app.extensions import db
    from app.models import PersonnelDocumentUploadBatch

    with app.app_context():
        # Whole transaction (including the pre-created batch row) rolled back.
        assert db.session.query(PersonnelDocumentUploadBatch).count() == 0


def test_document_bulk_upload_no_files_rejected(app, client):
    emp_id = _create_user(app, sicil_no="w2d008", email="w2d008@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgr008", email="w2mgr008@bys360.test", role="admin")
    _login(client, "w2mgr008")
    token = _set_token(client, "hr_personnel_document_bulk_upload", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/document/bulk-upload",
        data={"form_token": token, "user_id": str(emp_id), "category": "ozluk"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert _document_count(app) == 0


# ===========================================================================
# 4) PROCESS NOTES
# ===========================================================================


def test_note_save_creates_open_note(app, client):
    emp_id = _create_user(app, sicil_no="w2n001", email="w2n001@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrn001", email="w2mgrn001@bys360.test", role="admin")
    _login(client, "w2mgrn001")
    token = _set_token(client, "hr_personnel_note_save", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/note/save",
        data={
            "form_token": token,
            "user_id": str(emp_id),
            "note_type": "ozluk",
            "subject": "Özlük dosyası kontrolü",
            "note": "Yıllık kontrol yapıldı, eksik yok.",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    from app.extensions import db
    from app.models import PersonnelProcessNote

    with app.app_context():
        note = db.session.query(PersonnelProcessNote).one()
        assert note.status == "open"
        assert note.subject == "Özlük dosyası kontrolü"


def test_note_save_missing_required_fields_rejected(app, client):
    emp_id = _create_user(app, sicil_no="w2n002", email="w2n002@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrn002", email="w2mgrn002@bys360.test", role="admin")
    _login(client, "w2mgrn002")
    token = _set_token(client, "hr_personnel_note_save", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/note/save",
        data={"form_token": token, "user_id": str(emp_id), "subject": "", "note": ""},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    from app.extensions import db
    from app.models import PersonnelProcessNote

    with app.app_context():
        assert db.session.query(PersonnelProcessNote).count() == 0


def test_note_toggle_closes_then_reopens(app, client):
    emp_id = _create_user(app, sicil_no="w2n003", email="w2n003@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrn003", email="w2mgrn003@bys360.test", role="admin")
    _login(client, "w2mgrn003")

    from app.extensions import db
    from app.models import PersonnelProcessNote

    with app.app_context():
        note = PersonnelProcessNote(user_id=emp_id, subject="Kontrol notu", note="içerik", status="open")
        db.session.add(note)
        db.session.commit()
        note_id = note.id

    token1 = _set_token(client, "hr_personnel_note_close", "hr_personnel_operations")
    resp1 = client.post(
        f"/hr-management/personnel-operations/note/{note_id}/toggle",
        data={"form_token": token1, "user_id": str(emp_id)},
        follow_redirects=False,
    )
    assert resp1.status_code == 302
    with app.app_context():
        updated = db.session.get(PersonnelProcessNote, note_id)
        assert updated is not None
        assert updated.status == "closed"
        assert updated.resolved_at is not None

    token2 = _set_token(client, "hr_personnel_note_close", "hr_personnel_operations")
    resp2 = client.post(
        f"/hr-management/personnel-operations/note/{note_id}/toggle",
        data={"form_token": token2, "user_id": str(emp_id)},
        follow_redirects=False,
    )
    assert resp2.status_code == 302
    with app.app_context():
        updated = db.session.get(PersonnelProcessNote, note_id)
        assert updated is not None
        assert updated.status == "open"
        assert updated.resolved_at is None


def test_note_delete_removes_row(app, client):
    emp_id = _create_user(app, sicil_no="w2n004", email="w2n004@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrn004", email="w2mgrn004@bys360.test", role="admin")
    _login(client, "w2mgrn004")

    from app.extensions import db
    from app.models import PersonnelProcessNote

    with app.app_context():
        note = PersonnelProcessNote(user_id=emp_id, subject="Silinecek", note="içerik", status="open")
        db.session.add(note)
        db.session.commit()
        note_id = note.id

    token = _set_token(client, "hr_personnel_note_delete", "hr_personnel_operations")
    resp = client.post(
        f"/hr-management/personnel-operations/note/{note_id}/delete",
        data={"form_token": token, "user_id": str(emp_id)},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        assert db.session.query(PersonnelProcessNote).count() == 0


def test_note_save_wrong_scope_denied_no_row_created(app):
    """A birim_sorumlusu manager cannot write a process note for an employee
    outside their scope (different, unrelated unit)."""
    _create_user(app, sicil_no="w2mgrn005", email="w2mgrn005@bys360.test", role="birim_sorumlusu", birim="IK")
    emp_other = _create_user(app, sicil_no="w2empn005", email="w2empn005@bys360.test", role="personel", birim="Finans")

    mgr_client = app.test_client()
    _login(mgr_client, "w2mgrn005")
    token = _set_token(mgr_client, "hr_personnel_note_save", "hr_personnel_operations")

    resp = mgr_client.post(
        "/hr-management/personnel-operations/note/save",
        data={
            "form_token": token,
            "user_id": str(emp_other),
            "subject": "Kapsam dışı not",
            "note": "Bu not oluşturulmamalı",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    from app.extensions import db
    from app.models import PersonnelProcessNote

    with app.app_context():
        assert db.session.query(PersonnelProcessNote).count() == 0


# ===========================================================================
# 5) STATUS HISTORY
# ===========================================================================


def test_status_save_creates_row_with_required_fields(app, client):
    emp_id = _create_user(app, sicil_no="w2s001", email="w2s001@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrs001", email="w2mgrs001@bys360.test", role="admin")
    _login(client, "w2mgrs001")
    token = _set_token(client, "hr_personnel_status_save", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/status/save",
        data={
            "form_token": token,
            "user_id": str(emp_id),
            "event_type": "terfi",
            "event_date": "2026-08-01",
            "summary": "Kıdemli uzmanlığa terfi",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    from app.extensions import db
    from app.models import PersonnelStatusHistory

    with app.app_context():
        row = db.session.query(PersonnelStatusHistory).one()
        assert row.summary == "Kıdemli uzmanlığa terfi"
        assert row.event_type == "terfi"


def test_status_save_missing_summary_or_date_rejected(app, client):
    emp_id = _create_user(app, sicil_no="w2s002", email="w2s002@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrs002", email="w2mgrs002@bys360.test", role="admin")
    _login(client, "w2mgrs002")
    token = _set_token(client, "hr_personnel_status_save", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/status/save",
        data={"form_token": token, "user_id": str(emp_id), "event_type": "terfi", "summary": ""},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    from app.extensions import db
    from app.models import PersonnelStatusHistory

    with app.app_context():
        assert db.session.query(PersonnelStatusHistory).count() == 0


def test_status_delete_removes_row(app, client):
    emp_id = _create_user(app, sicil_no="w2s003", email="w2s003@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrs003", email="w2mgrs003@bys360.test", role="admin")
    _login(client, "w2mgrs003")

    import datetime as dt

    from app.extensions import db
    from app.models import PersonnelStatusHistory

    with app.app_context():
        row = PersonnelStatusHistory(user_id=emp_id, event_type="durum", event_date=dt.date(2026, 1, 1), summary="Silinecek kayıt")
        db.session.add(row)
        db.session.commit()
        row_id = row.id

    token = _set_token(client, "hr_personnel_status_delete", "hr_personnel_operations")
    resp = client.post(
        f"/hr-management/personnel-operations/status/{row_id}/delete",
        data={"form_token": token, "user_id": str(emp_id)},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        assert db.session.query(PersonnelStatusHistory).count() == 0


# ===========================================================================
# 6) POSITION HISTORY
# ===========================================================================


def test_position_save_creates_row_and_sets_is_current(app, client):
    emp_id = _create_user(app, sicil_no="w2pos001", email="w2pos001@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrpos001", email="w2mgrpos001@bys360.test", role="admin")
    _login(client, "w2mgrpos001")
    token = _set_token(client, "hr_personnel_position_save", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/position/save",
        data={
            "form_token": token,
            "user_id": str(emp_id),
            "position_title": "Uzman",
            "start_date": "2026-01-01",
            "is_current": "1",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    from app.extensions import db
    from app.models import PersonnelPositionHistory

    with app.app_context():
        row = db.session.query(PersonnelPositionHistory).one()
        assert row.position_title == "Uzman"
        assert row.is_current is True


def test_position_save_second_is_current_unsets_previous(app, client):
    emp_id = _create_user(app, sicil_no="w2pos002", email="w2pos002@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrpos002", email="w2mgrpos002@bys360.test", role="admin")
    _login(client, "w2mgrpos002")

    token1 = _set_token(client, "hr_personnel_position_save", "hr_personnel_operations")
    client.post(
        "/hr-management/personnel-operations/position/save",
        data={
            "form_token": token1,
            "user_id": str(emp_id),
            "position_title": "Uzman Yardımcısı",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "is_current": "1",
        },
        follow_redirects=False,
    )

    from app.extensions import db
    from app.models import PersonnelPositionHistory

    with app.app_context():
        first_row = db.session.query(PersonnelPositionHistory).one()
        assert first_row.is_current is True
        first_id = first_row.id

    token2 = _set_token(client, "hr_personnel_position_save", "hr_personnel_operations")
    resp = client.post(
        "/hr-management/personnel-operations/position/save",
        data={
            "form_token": token2,
            "user_id": str(emp_id),
            "position_title": "Uzman",
            "start_date": "2026-01-01",
            "is_current": "1",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        rows = db.session.query(PersonnelPositionHistory).order_by(PersonnelPositionHistory.id.asc()).all()
        assert len(rows) == 2
        older = next(r for r in rows if r.id == first_id)
        newer = next(r for r in rows if r.id != first_id)
        assert older.is_current is False  # uniqueness update applied
        assert newer.is_current is True


def test_position_save_end_date_before_start_date_rejected(app, client):
    emp_id = _create_user(app, sicil_no="w2pos003", email="w2pos003@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrpos003", email="w2mgrpos003@bys360.test", role="admin")
    _login(client, "w2mgrpos003")
    token = _set_token(client, "hr_personnel_position_save", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/position/save",
        data={
            "form_token": token,
            "user_id": str(emp_id),
            "position_title": "Geçersiz tarih testi",
            "start_date": "2026-06-01",
            "end_date": "2026-01-01",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    from app.extensions import db
    from app.models import PersonnelPositionHistory

    with app.app_context():
        assert db.session.query(PersonnelPositionHistory).count() == 0


def test_position_delete_removes_row(app, client):
    emp_id = _create_user(app, sicil_no="w2pos004", email="w2pos004@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrpos004", email="w2mgrpos004@bys360.test", role="admin")
    _login(client, "w2mgrpos004")

    from app.extensions import db
    from app.models import PersonnelPositionHistory

    with app.app_context():
        row = PersonnelPositionHistory(user_id=emp_id, position_title="Silinecek pozisyon")
        db.session.add(row)
        db.session.commit()
        row_id = row.id

    token = _set_token(client, "hr_personnel_position_delete", "hr_personnel_operations")
    resp = client.post(
        f"/hr-management/personnel-operations/position/{row_id}/delete",
        data={"form_token": token, "user_id": str(emp_id)},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        assert db.session.query(PersonnelPositionHistory).count() == 0


def test_position_delete_wrong_scope_denied(app):
    _create_user(app, sicil_no="w2mgrposD", email="w2mgrposD@bys360.test", role="birim_sorumlusu", birim="IK")
    emp_other = _create_user(app, sicil_no="w2emposD", email="w2emposD@bys360.test", role="personel", birim="Finans")

    from app.extensions import db
    from app.models import PersonnelPositionHistory

    with app.app_context():
        row = PersonnelPositionHistory(user_id=emp_other, position_title="Kapsam dışı pozisyon")
        db.session.add(row)
        db.session.commit()
        row_id = row.id

    mgr_client = app.test_client()
    _login(mgr_client, "w2mgrposD")
    token = _set_token(mgr_client, "hr_personnel_position_delete", "hr_personnel_operations")

    resp = mgr_client.post(
        f"/hr-management/personnel-operations/position/{row_id}/delete",
        data={"form_token": token, "user_id": str(emp_other)},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        assert db.session.query(PersonnelPositionHistory).count() == 1


# ===========================================================================
# 7) VALIDITY CENTER
# ===========================================================================


def test_validity_center_loads_for_manager(app, client):
    _create_user(app, sicil_no="w2v001", email="w2v001@bys360.test", role="admin")
    _login(client, "w2v001")

    resp = client.get("/hr-management/personnel-operations/validity-center")

    assert resp.status_code == 200


def test_validity_center_denied_for_non_manager(app, client):
    _create_user(app, sicil_no="w2v002", email="w2v002@bys360.test", role="personel")
    _login(client, "w2v002")

    resp = client.get("/hr-management/personnel-operations/validity-center")

    assert resp.status_code == 403


# ===========================================================================
# 8) UNAUTHENTICATED ACCESS TO WRITE ROUTES
# ===========================================================================


def test_unauthenticated_self_service_save_redirects_to_login_no_row_created(app, client):
    resp = client.post(
        "/hr-management/self-service/requests/save",
        data={"title": "t", "description": "d", "action_mode": "draft"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")
    assert _self_service_request_count(app) == 0


def test_unauthenticated_document_save_redirects_to_login(app, client):
    resp = client.post(
        "/hr-management/personnel-operations/document/save",
        data={"user_id": "1", "title": "t"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")


def test_non_manager_document_save_denied(app, client):
    emp_id = _create_user(app, sicil_no="w2np001", email="w2np001@bys360.test", role="personel")
    _login(client, "w2np001")
    token = _set_token(client, "hr_personnel_document_save", "hr_personnel_operations")

    resp = client.post(
        "/hr-management/personnel-operations/document/save",
        data={"form_token": token, "user_id": str(emp_id), "title": "Yasak deneme"},
        follow_redirects=False,
    )

    assert resp.status_code == 403
    assert _document_count(app) == 0


# ===========================================================================
# 9) BROAD `except Exception` FALLBACK -- REAL DB-ERROR DEGRADATION
# ===========================================================================


def test_self_service_request_save_commit_failure_degrades_safely_no_partial_row(app, client, monkeypatch):
    """Exercises the route's own ``except Exception`` block
    (``hr_self_service_request_save``, around ``db.session.commit()``) with a
    genuine DB-layer failure, proving the route degrades to a safe
    flash+redirect instead of a raw 500/half-written row."""
    _create_user(app, sicil_no="w2ex001", email="w2ex001@bys360.test", role="personel")
    _login(client, "w2ex001")
    token = _set_token(client, "hr_self_service_request_save", "hr_self_service_requests")

    import app.institutional.hr_personnel_operations_routes as target

    def _raise_on_commit():
        raise RuntimeError("simulated commit failure for phase5w2 rollback test")

    monkeypatch.setattr(target.db.session, "commit", _raise_on_commit)

    resp = client.post(
        "/hr-management/self-service/requests/save",
        data={"form_token": token, "title": "Çöken kayıt", "description": "d", "action_mode": "draft"},
        follow_redirects=False,
    )

    assert resp.status_code == 302  # safe redirect, not a raw 500

    monkeypatch.undo()
    assert _self_service_request_count(app) == 0


def test_document_save_commit_failure_degrades_safely_no_partial_row(app, client, monkeypatch):
    """Exercises the ``except Exception`` block in ``hr_personnel_document_save``."""
    emp_id = _create_user(app, sicil_no="w2ex002", email="w2ex002@bys360.test", role="personel")
    _create_user(app, sicil_no="w2mgrex002", email="w2mgrex002@bys360.test", role="admin")
    _login(client, "w2mgrex002")
    token = _set_token(client, "hr_personnel_document_save", "hr_personnel_operations")

    import app.institutional.hr_personnel_operations_routes as target

    def _raise_on_commit():
        raise RuntimeError("simulated commit failure for phase5w2 document save")

    monkeypatch.setattr(target.db.session, "commit", _raise_on_commit)

    resp = client.post(
        "/hr-management/personnel-operations/document/save",
        data={
            "form_token": token,
            "user_id": str(emp_id),
            "category": "ozluk",
            "title": "Çöken belge kaydı",
            "document_file": _pdf(),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302

    monkeypatch.undo()
    assert _document_count(app) == 0


def test_personnel_request_review_commit_failure_degrades_safely_status_unchanged(app, client, monkeypatch):
    """Exercises the ``except Exception`` block in ``hr_personnel_request_review``."""
    _create_user(app, sicil_no="w2exm003", email="w2exm003@bys360.test", role="admin")
    emp_id = _create_user(app, sicil_no="w2exe003", email="w2exe003@bys360.test", role="personel")

    from app.core.datetime_utils import utc_now
    from app.extensions import db
    from app.models.hr_models import PersonnelSelfServiceRequest

    with app.app_context():
        row = PersonnelSelfServiceRequest(
            user_id=emp_id, created_by_id=emp_id, title="Commit hatası testi", description="d",
            request_type="belge_talebi", priority="normal", status="submitted", submitted_at=utc_now(),
        )
        db.session.add(row)
        db.session.commit()
        req_id = row.id

    _login(client, "w2exm003")
    token = _set_token(client, "hr_personnel_request_review", "hr_personnel_operations")

    import app.institutional.hr_personnel_operations_routes as target

    def _raise_on_commit():
        raise RuntimeError("simulated commit failure for phase5w2 review")

    monkeypatch.setattr(target.db.session, "commit", _raise_on_commit)

    resp = client.post(
        f"/hr-management/personnel-operations/request/{req_id}/review",
        data={"form_token": token, "review_action": "approve", "decision_note": "x"},
        follow_redirects=False,
    )

    assert resp.status_code == 302

    monkeypatch.undo()
    with app.app_context():
        updated = db.session.get(PersonnelSelfServiceRequest, req_id)
        assert updated is not None
        assert updated.status == "submitted"
