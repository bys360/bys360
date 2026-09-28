"""BYS360 H1F -- final fresh residual audit (coordinator-level), route-layer
findings not covered by any of the 3 H1F-A/B/C agent waves.

The single highest-reach finding in this pass is app/route_support.py's
safe_render() -- the shared template-rendering wrapper used by nearly every
route in this codebase. Its exception fallback used to (a) flash a raw
exception string to the user and (b) return raw, unescaped HTML containing
the exception text as the page body itself
(f"<h3>{template_name} sablonu hatali</h3><p>{exc}</p>"). Fixed to a fixed
safe message in both places.

For the remaining ~25 route-level findings (communication, HR/institutional,
admin, main_handlers/account, and performance routes, plus the meeting P0-P4
workflow routes) -- all the exact same mechanical shape as the ones H1F-A
already fixed and tested (flash(f"...: {exc}") -> flash("...") with
logger.exception preserved/added) -- this file:
  (a) full-behavior-tests a representative sample across each domain
      (communication, HR, admin, account settings, performance, meeting
      workflow) to prove the end-to-end pattern is genuinely fixed, not just
      textually similar, and
  (b) source-level regression-guards the rest, matching the precedent set by
      H1F-A's and this wave's own AI-decision-support test file for
      mechanically-identical repeated fixes across many sibling files --
      re-deriving full login/DB/CSRF fixtures for every one of ~20 near-
      identical single-line flash fixes would not prove anything the
      representative behavioral tests do not already prove, and risks
      silently drifting out of sync with the source as a maintenance burden.

Writes NOTHING to any production source file.
"""
from __future__ import annotations

import logging
import pathlib
import tempfile
import uuid
from pathlib import Path

import pytest

_SENTINEL = "TECHNICAL_SENTINEL_DO_NOT_SHOW_9F3A"
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PASSWORD = "H1FFinalAuditRouteTest1!"
_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1f_final_audit_route_layer_tmp" / "test_dbs"


def _raise_sentinel(*_args, **_kwargs):
    raise Exception(_SENTINEL)  # noqa: TRY002 - deliberately generic


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1f-final-audit-route-layer")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1f-final-audit-route-layer-first-login-test-pw")
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
            soyad="FinalAuditRouteLayer",
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
# 1) app/route_support.py -- safe_render(). The single highest-reach finding:
#    this wrapper is used by nearly every route in the app.
# ---------------------------------------------------------------------------


def test_safe_render_template_failure_never_leaks_raw_exception_in_flash_or_body(app, caplog) -> None:
    import app.route_support as route_support_mod

    def _raise_jinja_error(*_a, **_k):
        raise Exception(_SENTINEL)  # noqa: TRY002

    with (
        app.test_request_context("/"),
        caplog.at_level(logging.ERROR, logger="app.route_support"),
        pytest.MonkeyPatch.context() as mp,
    ):
        mp.setattr(route_support_mod, "flask_render_template", _raise_jinja_error)
        body = route_support_mod.safe_render("does_not_matter.html", "")

    assert _SENTINEL not in body
    assert "Sayfa gösterilirken bir hata oluştu" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


def test_safe_render_uses_caller_fallback_html_when_provided(app) -> None:
    import app.route_support as route_support_mod

    with app.test_request_context("/"), pytest.MonkeyPatch.context() as mp:
        mp.setattr(route_support_mod, "flask_render_template", _raise_sentinel)
        body = route_support_mod.safe_render("does_not_matter.html", "<h3>Özel geri dönüş</h3>")

    assert _SENTINEL not in body
    assert body == "<h3>Özel geri dönüş</h3>"


# ---------------------------------------------------------------------------
# 2) app/communication/notifications_routes.py -- representative of the
#    communication-domain fixes (announcements_routes.py is the sibling,
#    source-guarded below).
# ---------------------------------------------------------------------------


def test_notifications_mark_all_read_db_failure_never_leaks_raw_exception(app, client, caplog) -> None:
    _create_user(app, sicil_no="h1f_notif_user", role="personel")
    _login(client, "h1f_notif_user")

    import app.communication.notifications_routes as notif_routes

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(notif_routes.db.session, "commit", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.communication.notifications_routes"):
            resp = client.post("/notifications/mark-all-read", follow_redirects=True)

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Bildirimler güncellenirken hata oluştu" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 3) app/institutional/hr_common.py -- _safe_commit, shared by several HR
#    forms (leave, attendance, delegation).
# ---------------------------------------------------------------------------


def test_hr_common_safe_commit_db_failure_never_leaks_raw_exception(app, monkeypatch, caplog) -> None:
    import app.institutional.hr_common as hr_common_mod

    class _FakeSession:
        def commit(self):
            raise Exception(_SENTINEL)  # noqa: TRY002

        def rollback(self):
            pass

    monkeypatch.setattr(hr_common_mod, "db", type("_D", (), {"session": _FakeSession()})())

    captured: dict = {}

    def _fake_flash(message, category):
        captured["message"] = message
        captured["category"] = category

    with app.test_request_context("/"), caplog.at_level(logging.ERROR, logger="app.institutional.hr_common"):
        monkeypatch.setattr(hr_common_mod, "flash", _fake_flash)
        result = hr_common_mod._safe_commit("Kaydedildi.", danger_prefix="Kayıt işlemi başarısız oldu")

    assert result is False
    assert _SENTINEL not in captured["message"]
    assert captured["message"] == "Kayıt işlemi başarısız oldu."
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 4) app/performance/task_routes.py -- representative of the performance
#    route fixes.
# ---------------------------------------------------------------------------


def test_performance_task_generation_failure_never_leaks_raw_exception(app, client, caplog) -> None:
    _create_user(app, sicil_no="h1f_task_admin", role="admin")
    _login(client, "h1f_task_admin")

    import app.performance.task_routes as task_routes_mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(task_routes_mod, "generate_assignments_for_active_period", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.performance.task_routes"):
            resp = client.post("/performance/task-management/generate", data={"force_generate": "1"}, follow_redirects=True)

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "Görev üretimi sırasında hata oluştu" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 5) meeting P0 workflow route -- representative of the meeting_p0..p4 +
#    meeting_rule_enforcement fixes (all share the identical
#    warnings.append(f"...: {exc}") -> flash(warning) shape).
# ---------------------------------------------------------------------------


def test_meeting_p0_completion_apply_failure_never_leaks_raw_exception(app, client, caplog) -> None:
    _create_user(app, sicil_no="h1f_p0_manager", role="admin")
    _login(client, "h1f_p0_manager")

    import app.services.performance.meeting_p0_completion as p0_mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(p0_mod, "ensure_p0_settings", _raise_sentinel)

        with caplog.at_level(logging.ERROR, logger="app.services.performance.meeting_p0_completion"):
            resp = client.post("/performance/meeting-development/p0/apply", follow_redirects=True)

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert _SENTINEL not in body
    assert "P0 temel veri hazırlığı tamamlanamadı" in body
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# Source-level regression guards for the remaining, mechanically-identical
# route-layer fixes in this final-audit pass (see module docstring).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("relative_path", "forbidden_snippets"),
    [
        ("app/communication/announcements_routes.py", ['flash(f"Duyuru gönderilirken hata oluştu: {exc}"']),
        ("app/institutional/hr_leave_attendance_routes.py", ['flash(f"Durum güncellenemedi: {exc}"', 'flash(f"Kayıt silinemedi: {exc}"']),
        ("app/institutional/hr_reports_routes.py", ['flash(f"Personel özlük ekranı geçici olarak açılamadı: {exc}"']),
        (
            "app/institutional/org_unit_routes.py",
            [
                'flash(f"Birim oluşturulurken hata oluştu: {exc}"',
                'flash(f"Birim güncellenirken hata oluştu: {exc}"',
                'flash(f"Birim durumu güncellenirken hata oluştu: {exc}"',
                'flash(f"Birim ekleme sırasında hata oluştu: {exc}"',
                'flash(f"Birim güncelleme sırasında hata oluştu: {exc}"',
                'flash(f"Silme işlemi sırasında hata oluştu: {exc}"',
            ],
        ),
        ("app/admin/ops_import_services.py", ['birim oluşturulamadı -> {exc}', 'errors.append(f"Satır {rowno}: {exc}")']),
        (
            # NOTE: the photo-update site's flash(f"...: {exc}") was
            # deliberately reintroduced in a ValueError-only branch after
            # the domain regression suite caught that its original,
            # generic `except Exception` version was silently swallowing a
            # genuinely safe, hand-authored validation message from
            # app/services/profile_photo_service.py's own ValueError (see
            # tests/behavior/test_admin_ops_user_actions_destructive_
            # operations_contract.py::test_admin_user_change_photo_invalid_
            # extension_rejected_with_no_mutation) -- so it is intentionally
            # NOT in this file's forbidden-snippet list.
            "app/admin/ops_user_action_services.py",
            [
                'flash(f"Arşivleme sırasında hata oluştu: {exc}"',
                'flash(f"Bu kullanıcı silinemedi: {exc}"',
                'flash(f"Kullanıcı durumu güncellenirken hata oluştu: {exc}"',
                'flash(f"Sıfırlama işlemi sırasında hata oluştu: {exc}"',
            ],
        ),
        ("app/main_handlers/account_handlers.py", ['flash(f"Profil fotoğrafı güncellenirken hata oluştu: {exc}"']),
        ("app/main_handlers/account_settings_helpers.py", ['{exc}", "danger")']),
        (
            "app/performance/engagement_feedback_routes.py",
            [
                'flash(f"Takip uyarıları çalıştırılırken hata oluştu: {exc}"',
                'flash(f"Yönetici özeti çalıştırılırken hata oluştu: {exc}"',
                'flash(f"Randevu oluşturulurken hata oluştu: {exc}"',
            ],
        ),
        (
            "app/performance/engagement_publish_routes.py",
            [
                'flash(f"Snapshot backfill sırasında hata oluştu: {exc}"',
                'flash(f"Toplu yayın sırasında hata oluştu: {exc}"',
                'flash(f"Toplu yayından kaldırma sırasında hata oluştu: {exc}"',
                'flash(f"Tekil yayın sırasında hata oluştu: {exc}"',
                'flash(f"Tekil yayından kaldırma sırasında hata oluştu: {exc}"',
            ],
        ),
        ("app/performance/hierarchy_ui_routes.py", ['flash(f"Hiyerarşi ataması kaydedilirken hata oluştu: {exc}"']),
        ("app/performance/history_import_routes.py", ['flash(f"Excel dosyası okunamadı: {exc}"', 'flash(f"Aktarım sırasında hata oluştu: {exc}"']),
        ("app/performance/meeting_p4_development_guidance_routes.py", ['flash(f"Gelişim rehberi kaydı alınamadı: {exc}"']),
        (
            "app/performance/routes.py",
            [
                'flash(f"Amir atamaları kaydedilirken hata oluştu: {exc}"',
                'flash(f"Otomatik amir zinciri kurulurken hata oluştu: {exc}"',
                'flash(f"Ağırlık ayarları kaydedilirken hata oluştu: {exc}"',
                'flash(f"Amir zinciri kaydedilirken hata oluştu: {exc}"',
            ],
        ),
        ("app/performance/task_routes.py", ['flash(f"Görev üretimi sırasında hata oluştu: {exc}"', 'flash(f"Görevler temizlenirken hata oluştu: {exc}"']),
        ("app/performance/v2_1_4_category_scope_routes.py", ['flash(f"Kategori kapsam işlemi tamamlanamadı: {exc}"']),
        ("app/performance/v2_1_5_category_period_scope_routes.py", ['flash(f"Kapsam işlemi tamamlanamadı: {exc}"']),
        ("app/performance/v2_1_6_category_period_integration_routes.py", ['flash(f"Dönem entegrasyonu tamamlanamadı: {exc}"']),
        ("app/performance/performance_archive_routes.py", ['flash(f"Excel aktarımı yapılamadı: {exc}"']),
        ("app/performance/v2_1_3_personnel_category_card_routes.py", ['flash(f"Kategori işlemi tamamlanamadı: {exc}"']),
        ("app/services/performance/meeting_p1_scope.py", ['warnings.append(f"P1 geliştirme hazırlığı tamamlanamadı: {exc}")']),
        (
            "app/services/performance/meeting_p2_archive_notes.py",
            [
                'warnings.append(f"Geçmiş karne arşiv tablosu oluşturulamadı: {exc}")',
                'warnings.append(f"Ara dönem not tablosu oluşturulamadı: {exc}")',
                'warnings.append(f"P2 arşiv/ara not hazırlığı tamamlanamadı: {exc}")',
            ],
        ),
        (
            "app/services/performance/meeting_p3_reminders.py",
            [
                'warnings.append(f"Hatırlatma kuyruğu tablosu oluşturulamadı: {exc}")',
                'warnings.append(f"Aksatan amir özet tablosu oluşturulamadı: {exc}")',
                'warnings.append(f"Faz 9 hatırlatma hazırlığı tamamlanamadı: {exc}")',
            ],
        ),
        (
            "app/services/performance/meeting_p4_development_guidance.py",
            [
                'warnings.append(f"Gelişim önerisi tablosu oluşturulamadı: {exc}")',
                'warnings.append(f"Aşama 10 gelişim/rehberlik hazırlığı tamamlanamadı: {exc}")',
            ],
        ),
        (
            "app/services/performance/meeting_rule_enforcement.py",
            [
                'warnings.append(f"Düşük performans süreç kontrolü uygulanamadı: {exc}")',
                'message=f"Kural uygulama sırasında hata oluştu: {exc}"',
            ],
        ),
        ("app/services/performance/feedback_aftercare_phase7_person_period.py", ['raise ValueError(f"Görüşme kaydı oluşturulamadı: {exc}")']),
        ("app/services/performance/process_engine_phase6_president_approvals.py", ['Phase6ActionResult(False, f"Kayıt silinemedi: {exc}"']),
        ("app/services/sp1d_target_management_service.py", ['return False, f"Kayıt oluşturulamadı: {exc}"', 'return False, f"Güncelleme tamamlanamadı: {exc}"']),
        ("app/services/performance/v2_1_7_period_management_center_gate.py", ['checks.append(_check("exception", False, str(exc)))']),
        ("app/services/performance/v2_1_8_period_center_assignment_launch_gate.py", ['checks.append(_check("exception", False, str(exc)))']),
        ("app/services/performance/v2_1_quality_gate.py", ['f"Kural motoru hatası: {exc}"', 'f"module_settings kontrol hatası: {exc}"']),
    ],
)
def test_route_or_service_source_no_longer_contains_raw_exception_interpolation(relative_path: str, forbidden_snippets: list[str]) -> None:
    source = (_PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
    for snippet in forbidden_snippets:
        assert snippet not in source, f"{relative_path}: still contains raw exception interpolation: {snippet!r}"
