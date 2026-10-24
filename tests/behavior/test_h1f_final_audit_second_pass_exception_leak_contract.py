"""BYS360 H1F -- final residual audit, SECOND pass.

The coordinator's own first residual-audit pass (see
test_h1f_final_audit_route_layer_exception_leak_contract.py and
test_h1f_final_audit_service_layer_exception_leak_contract.py) used a grep
pattern for f-string exception interpolation that only matched double-quoted
f-strings (f"...{exc}..."). A second, corrected pass -- matching BOTH
double- and single-quoted f-strings -- found ~26 more genuine confirmed
leaks the first pass's grep silently missed, concentrated in:

  - app/admin/routes.py (5 sites) -- the main Personnel CRUD admin screens
    (create/edit/add/update/Excel-upload), a very high-traffic surface that
    somehow evaded every prior wave's grep too.
  - app/admin/ops_routes.py (2 sites) -- personnel status-toggle/delete.
  - app/admin/ai_routes.py (3 sites) -- AI recommendation status update,
    AI redaction rule create/update.
  - app/admin/ai_phase5_routes.py (1 site, single-quoted f-string) -- AI
    bulk-operation failure.
  - app/ai_agent/routes.py (1 site, single-quoted f-string) -- Virtual
    Assistant knowledge-entry creation.
  - app/communication/phase8_routes.py, phase9_routes.py, phase9a_routes.py,
    phase9b_routes.py, phase9c_routes.py, phase9d_routes.py (14 sites total,
    ALL single-quoted f-strings) -- the go-live/cutover checkpoint-recording
    family H1E-A already humanized the STATUS labels for, but whose own
    technical-exception paths were never touched by H1F until now.
  - app/performance/performance_archive_routes.py (1 more site, a create-
    record path distinct from the import-Excel path H1F-B/coordinator
    already fixed).

Every fix is the same standard mechanical swap already proven throughout
H1F: flash(f"...: {exc}") -> flash("...") (or the single-quoted
equivalent), with logger.exception() preserved/extended to include the
exception detail server-side.

This file (a) full-behavior-tests representative sites across the two new
clusters (admin personnel CRUD, and one communication go-live checkpoint
family member) to prove the pattern is genuinely closed end-to-end, and
(b) source-level regression-guards the remaining mechanically-identical
sites, consistent with the precedent set throughout this whole effort for
sweeping, single-shape fixes across many sibling files/routes.

Writes NOTHING to any production source file.
"""
from __future__ import annotations

import logging
import pathlib
import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_SENTINEL = "TECHNICAL_SENTINEL_DO_NOT_SHOW_9F3A"
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PASSWORD = "H1FFinalAuditSecondPassTest1!"
_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1f_final_audit_second_pass_tmp" / "test_dbs"


def _raise_sentinel(*_args, **_kwargs):
    raise Exception(_SENTINEL)  # noqa: TRY002 - deliberately generic


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1f-final-audit-second-pass")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1f-final-audit-second-pass-first-login-test-pw")
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
        db.engine.dispose()

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
            ad="H1F",
            soyad="FinalAuditSecondPass",
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


# ---------------------------------------------------------------------------
# 1) app/admin/routes.py -- personnel_add (representative of the 5-site
#    Personnel CRUD cluster).
# ---------------------------------------------------------------------------


def test_admin_personnel_add_db_failure_never_leaks_raw_exception(app, client, caplog) -> None:
    _create_user(app, sicil_no="h1f_personnel_admin", role="admin")
    _login(client, "h1f_personnel_admin")

    import app.admin.routes as admin_routes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(admin_routes.db.session, "commit", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.admin.routes"):
            resp = client.post(
                "/personnel/add",
                data={
                    "ad": "Test", "soyad": "Personel", "sicil_no": "99999",
                    "email": "test.personel@ktb.gov.tr", "role": "personel",
                    "unvan": "Uzman", "birim": "Test Birimi", "ust_birim": "Test Genel Müdürlük",
                },
                follow_redirects=True,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Personel ekleme sırasında hata oluştu" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# app/admin/ops_user_action_services.py -- admin_user_change_photo_impl.
# The domain regression suite caught that this route's ORIGINAL H1F fix
# (a single generic `except Exception` sanitized to a fixed message) had
# silently swallowed a legitimate, hand-authored ValueError from
# app/services/profile_photo_service.py::save_profile_photo (a real
# business-validation message, "Sadece PNG, JPG, JPEG veya WEBP dosyaları
# yükleyebilirsiniz.") -- see tests/behavior/test_admin_ops_user_actions_
# destructive_operations_contract.py::test_admin_user_change_photo_invalid_
# extension_rejected_with_no_mutation, which already proves that branch.
# Fixed by splitting into a ValueError branch (message preserved) and a
# generic Exception branch (sanitized). This test proves the SECOND half:
# a genuinely unexpected exception (not the validation ValueError) still
# never leaks raw technical detail.
# ---------------------------------------------------------------------------


def test_admin_user_change_photo_unexpected_db_failure_never_leaks_raw_exception(app, client, caplog) -> None:
    import io

    _create_user(app, sicil_no="h1f_photo_admin", role="admin")
    target_id = _create_user(app, sicil_no="h1f_photo_target", role="personel")
    _login(client, "h1f_photo_admin")

    import app.admin.ops_user_action_services as ops_user_action_services

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ops_user_action_services, "_save_profile_photo", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.admin.ops_user_action_services"):
            resp = client.post(
                f"/admin/users/{target_id}/photo",
                data={"profile_photo": (io.BytesIO(b"fake-image-bytes"), "photo.png")},
                content_type="multipart/form-data",
                follow_redirects=True,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Profil fotoğrafı güncellenirken hata oluştu" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 2) app/communication/phase9c_routes.py -- gate creation (representative
#    of the 6-file, 14-site go-live/cutover checkpoint family).
# ---------------------------------------------------------------------------


def test_communication_phase9c_gate_create_db_failure_never_leaks_raw_exception(app, client, caplog) -> None:
    _create_user(app, sicil_no="h1f_phase9c_admin", role="admin")
    _login(client, "h1f_phase9c_admin")

    import app.communication.phase9c_routes as phase9c_routes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(phase9c_routes, "record_phase9c_gate", _raise_sentinel)
        mp.setattr(phase9c_routes, "consume_form_token", lambda *a, **k: True)

        with caplog.at_level(logging.ERROR, logger="app.communication.phase9c_routes"):
            resp = client.post(
                "/communication/faz9c/gate",
                data={"gate_key": "test_gate", "status": "pending", "note": "test"},
                follow_redirects=True,
            )

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Kapı kaydı oluşturulamadı" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# Source-level regression guards for the remaining mechanically-identical
# second-pass fixes (see module docstring).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("relative_path", "forbidden_snippets"),
    [
        (
            "app/admin/routes.py",
            [
                'flash(f"Personel oluşturulurken hata oluştu: {exc}"',
                'flash(f"Personel güncellenirken hata oluştu: {exc}"',
                'flash(f"Personel ekleme sırasında hata oluştu: {exc}"',
                'flash(f"Personel güncelleme sırasında hata oluştu: {exc}"',
                'flash(f"Excel yükleme sırasında hata oluştu: {exc}"',
            ],
        ),
        (
            "app/admin/ops_routes.py",
            [
                'flash(f"Durum güncelleme sırasında hata oluştu: {exc}"',
                'flash(f"Silme işlemi sırasında hata oluştu: {exc}"',
            ],
        ),
        (
            "app/admin/ai_routes.py",
            [
                'flash(f"AI öneri durumu güncellenemedi: {exc}"',
                'flash(f"AI maskeleme kuralı kaydedilemedi: {exc}"',
                'flash(f"AI maskeleme kuralı güncellenemedi: {exc}"',
            ],
        ),
        ("app/admin/ai_phase5_routes.py", ["flash(f'AI toplu işleminde hata oluştu: {exc}'"]),
        ("app/ai_agent/routes.py", ["flash(f'Bilgi kaydı oluşturulamadı: {exc}'"]),
        ("app/communication/phase8_routes.py", ["flash(f'Kontrol noktası kaydı oluşturulamadı: {exc}'", "flash(f'Pilot notu kaydedilemedi: {exc}'"]),
        ("app/communication/phase9_routes.py", ["flash(f'Kontrol noktası kaydı oluşturulamadı: {exc}'", "flash(f'Karar kaydedilemedi: {exc}'"]),
        ("app/communication/phase9a_routes.py", ["flash(f'Teknik kilit kaydı oluşturulamadı: {exc}'", "flash(f'Smoke kaydı işlenemedi: {exc}'"]),
        ("app/communication/phase9b_routes.py", ["flash(f'Kapı kaydı oluşturulamadı: {exc}'", "flash(f'Karar kaydı oluşturulamadı: {exc}'"]),
        (
            "app/communication/phase9c_routes.py",
            ["flash(f'Kapı kaydı oluşturulamadı: {exc}'", "flash(f'Karar kaydı oluşturulamadı: {exc}'", "flash(f'Olay kaydı oluşturulamadı: {exc}'"],
        ),
        (
            "app/communication/phase9d_routes.py",
            ["flash(f'Check-in kaydedilemedi: {exc}'", "flash(f'Hotfix kaydı oluşturulamadı: {exc}'", "flash(f'İzleme sinyali kaydedilemedi: {exc}'"],
        ),
        ("app/performance/performance_archive_routes.py", ['flash(f"Kayıt eklenemedi: {exc}"']),
    ],
)
def test_second_pass_source_no_longer_contains_raw_exception_interpolation(relative_path: str, forbidden_snippets: list[str]) -> None:
    source = (_PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
    for snippet in forbidden_snippets:
        assert snippet not in source, f"{relative_path}: still contains raw exception interpolation: {snippet!r}"
