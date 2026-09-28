"""BYS360 H1F -- app/services/**, app/ai/**, export/File Center service-layer
raw exception leak fixes (Agent 2 scope).

A repo-wide grep audit of app/services/**, app/ai/**, Excel/PDF export code
and File Center service functions found several places where a caught
backend exception's raw ``str(exc)`` text could reach a real end user
(usually an admin/manager) instead of a short, safe, curated Turkish
message -- the same anti-pattern H1E already closed for raw status/enum
values. Each fix below is covered by a dedicated test that:

  (a) triggers the fixed code path with a distinctive sentinel exception
      (``Exception("TECHNICAL_SENTINEL_DO_NOT_SHOW_9F3A")``),
  (b) asserts the sentinel never appears in the user-visible output,
  (c) asserts the new safe Turkish message is present instead, and
  (d) where a new ``logger.exception(...)`` call was added, asserts the
      exception was actually captured (via ``caplog``).

Fixed in this wave:

  1. app/file_center/services.py -- four ``except Exception as exc`` blocks
     (``_move_file_to_area``, ``release_quarantined_file``,
     ``cancel_chunk_upload_session``, the chunk-finalize cleanup) wrote
     ``f"...: {exc}"`` straight into ``FileAuditLog.message`` via
     ``log_audit(...)``. Confirmed reachable: this log is rendered verbatim
     as ``{{ row.message }}`` on the admin "Dosya Merkezi" logs screen
     (app/templates/file_center/logs.html:43) and as
     ``{{ scan.result_message }}`` on security.html:127. No operator
     logging existed before; added ``logger.exception(...)`` per site.

  2. app/services/performance/hardening_service.py::humanize_export_exception
     -- the Excel/PDF export error sanitizer had a final ``return raw``
     fallback that leaked the raw exception text for any exception whose
     message didn't match one of its curated substrings. Reachable via
     ``flash(f"...: {humanize_export_exception(exc)}", "danger")`` in six
     different route call sites (evaluation_core_routes.py,
     engagement_mail_routes.py, engagement_publish_routes.py,
     task_routes.py x3) -- all of which already log the raw exception via
     ``current_app.logger.exception(...)`` before calling this sanitizer,
     so no new logging was needed here.

  3. app/services/performance/evaluation_form_service.py::collect_item_payloads
     -- ``float(raw_score)`` and ``validate_score_value(...)`` shared one
     ``except ValueError as exc: flash(str(exc), ...)``. ``validate_score_value``
     itself only ever raises a fixed safe message, but Python's builtin
     ``float()`` parse failure (e.g. malformed form input) produced its own
     English technical ValueError text ("could not convert string to
     float: ...") that would have been flashed verbatim. Split into two
     try/except blocks so the float-parse failure gets its own fixed safe
     Turkish message.

  4. app/services/performance/core_health_panel.py -- ``_compact_task_health``
     and ``_compact_publish_preflight`` put ``str(exc)`` directly into a
     ``CoreFinding.detail``. Confirmed reachable: rendered as
     ``{{ row.detail }}`` in the admin-only "Çekirdek Sağlık Paneli"
     (app/templates/performance_core_health.html:14, route requires
     @admin_required). Operator logging already existed; only the
     user-visible detail text was sanitized.

  5. app/services/settings/foundation_access.py::ensure_settings_phase1_seeded_handler
     -- the seed-failure branch returned ``"error": str(exc)``. Confirmed
     reachable: app/main_handlers/account_settings_helpers.py (out of this
     agent's scope) does
     ``flash(f"Ayarlar omurgası hazırlanamadı: {phase1_seed_summary.get('error')}", 'warning')``
     on the live Ayarlar (Settings) admin screen. Fixed at the source dict
     so every downstream consumer of the "error" key is automatically safe.

  6. app/services/ai/preflight.py::_import_symbol -- returned
     ``(False, str(exc))`` for a failed internal import-chain check.
     Confirmed reachable: composed into ``f"Import hatası: {message}"``
     and rendered both on the admin "AI Preflight" screen
     (app/templates/admin_ai_preflight.html:73, ``{{ row.detail }}``) and
     exported verbatim as a CSV column
     (/admin/ai-preflight/export). No operator logging existed before;
     added ``logger.exception(...)``.

  7. app/services/ai_agent/service.py::_legacy_build_ai_agent_reply_fulltutor
     -- the safe-fallback reply dict (returned as the live JSON body of
     ``POST /ai_agent/api/ask`` when the AI tutor engine + its legacy
     builder both fail) carried an ``"error_note": str(exc)`` field
     alongside the already-safe "answer" text. The AI assistant feature
     itself is untouched -- only the technical debug field's value was
     replaced with a fixed safe note, and operator logging was added
     (there was none before this specific failure path).

Investigated and found NOT to be live leaks (traced to the actual
template/consumer and confirmed the raw exception text never reaches
render output) -- listed here only so the coordinator does not need to
re-derive this: app/services/ai/schema_guard.py (errors list stored but
never rendered; only the sibling fixed "message" is shown),
app/services/messages/{reactions,typing}.py and
app/services/ai_agent/action_queue_bridge.py (JSON API error field with no
current template/JS consumer -- API_MACHINE_CONTRACT_ONLY),
app/services/performance/visibility_guard.py (the exception-tainted
"publish_preflight.warnings" sub-dict is computed but never read by any
template -- confirmed by grepping every consumer up to
performance_scorecard_detail.html), and the v2_1_7/v2_1_8 quality-gate
dicts in app/performance/v2_1_7_period_management_center_routes.py
(passed to render_template but the template never references those
context keys).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import cast

_SENTINEL = "TECHNICAL_SENTINEL_DO_NOT_SHOW_9F3A"

# Repo-local scratch dir: pytest's own `tmp_path` fixture can fail with a
# PermissionError under some Windows profiles with non-ASCII usernames (see
# tests/conftest.py's BYS360_PHASE5_PYTEST_TEMP_CONTRACT note) -- so this
# file uses its own small scratch directory instead, matching the pattern
# other H1E/H1F test files in this repo already use.
_SCRATCH_ROOT = Path(__file__).resolve().parents[2] / "reports" / "quality" / "h1f_critical_service_test_scratch"


# ---------------------------------------------------------------------------
# 1. app/file_center/services.py
# ---------------------------------------------------------------------------


def test_file_center_move_file_to_area_failure_sanitizes_audit_message(app, monkeypatch, caplog):
    from app.file_center import services as fc_services
    from app.models.file_center_models import FileStorageItem

    captured: dict[str, object] = {}

    def _fake_log_audit(action, *, file_id=None, message=None, actor_user_id=None):
        captured["action"] = action
        captured["message"] = message

    monkeypatch.setattr(fc_services, "log_audit", _fake_log_audit)

    def _raise_move(*_args, **_kwargs):
        raise Exception(_SENTINEL)

    monkeypatch.setattr(fc_services.shutil, "move", _raise_move)

    _SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    source_file = _SCRATCH_ROOT / f"sample_upload_{uuid.uuid4().hex}.txt"
    source_file.write_text("data", encoding="utf-8")
    item = SimpleNamespace(id=42, storage_path=str(source_file), owner_user_id=7, stored_filename="sample_upload.txt")

    try:
        with app.app_context():
            caplog.set_level("ERROR")
            fc_services._move_file_to_area(cast(FileStorageItem, item), "quarantine")
    finally:
        # shutil.move is patched to fail, so the file stays; never leave it in the repo tree.
        source_file.unlink(missing_ok=True)

    assert captured.get("action") == "file_security_move_failed"
    message = str(captured.get("message") or "")
    assert _SENTINEL not in message
    assert "Dosya taşıma" in message
    assert any(_SENTINEL in str(getattr(r, "message", "")) or (r.exc_info and _SENTINEL in str(r.exc_info[1])) for r in caplog.records)


def test_file_center_cancel_chunk_upload_cleanup_failure_sanitizes_audit_message(monkeypatch, caplog):
    from app.file_center import services as fc_services

    captured_messages: list[str] = []

    def _fake_log_audit(action, *, file_id=None, message=None, actor_user_id=None):
        captured_messages.append(f"{action}:{message}")

    monkeypatch.setattr(fc_services, "log_audit", _fake_log_audit)

    def _raise_rmtree(*_args, **_kwargs):
        raise Exception(_SENTINEL)

    monkeypatch.setattr(fc_services.shutil, "rmtree", _raise_rmtree)

    session = SimpleNamespace(status="active", cancelled_at=None, temp_dir="C:/some/temp/dir", original_filename="ornek.xlsx", owner_user_id=7)

    class _FakeQuery:
        def get_or_404(self, _session_id):
            return session

    monkeypatch.setattr(fc_services, "FileUploadSession", SimpleNamespace(query=_FakeQuery()))

    caplog.set_level("ERROR")
    fc_services.cancel_chunk_upload_session(99, 7)

    joined = " | ".join(captured_messages)
    assert _SENTINEL not in joined
    assert "chunk_upload_cleanup_failed" in joined
    assert "temizlenirken bir hata oluştu" in joined
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 2. app/services/performance/hardening_service.py
# ---------------------------------------------------------------------------


def test_humanize_export_exception_unmatched_message_never_leaks_raw_text():
    from app.services.performance.hardening_service import humanize_export_exception

    safe = humanize_export_exception(Exception(_SENTINEL))
    assert _SENTINEL not in safe
    assert safe == "Dışa aktarma sırasında beklenmeyen bir hata oluştu."


def test_humanize_export_exception_still_maps_known_categories():
    from app.services.performance.hardening_service import humanize_export_exception

    assert "yetki" in humanize_export_exception(Exception("PermissionError: denied")).lower()


# ---------------------------------------------------------------------------
# 3. app/services/performance/evaluation_form_service.py
# ---------------------------------------------------------------------------


def test_collect_item_payloads_non_numeric_score_shows_safe_turkish_message(app):
    from app.services.performance.evaluation_form_service import collect_item_payloads

    criteria = [SimpleNamespace(id=1, name="Kriter 1")]
    form_data = {"score_1": "not-a-number", "comment_1": ""}

    with app.test_request_context("/performance/evaluate/1", method="POST"):
        result = collect_item_payloads(criteria, form_data)
        from flask import get_flashed_messages
        flashed = get_flashed_messages()

    assert result is None
    assert len(flashed) == 1
    first_message = flashed[0]
    assert isinstance(first_message, str)
    assert "could not convert" not in first_message.lower()
    assert first_message == "Puan değeri sayısal olmalıdır."


def test_collect_item_payloads_out_of_range_score_still_uses_fixed_business_message(app):
    from app.services.performance.evaluation_form_service import collect_item_payloads

    criteria = [SimpleNamespace(id=1, name="Kriter 1")]
    form_data = {"score_1": "9", "comment_1": ""}

    with app.test_request_context("/performance/evaluate/1", method="POST"):
        result = collect_item_payloads(criteria, form_data)
        from flask import get_flashed_messages
        flashed = get_flashed_messages()

    assert result is None
    assert flashed == ["Puan 1 ile 5 arasında olmalıdır."]


# ---------------------------------------------------------------------------
# 4. app/services/performance/core_health_panel.py
# ---------------------------------------------------------------------------


def test_compact_task_health_report_failure_is_sanitized(app, monkeypatch, caplog):
    from app.services.performance import core_health_panel

    def _raise(*_args, **_kwargs):
        raise Exception(_SENTINEL)

    monkeypatch.setattr(core_health_panel, "build_performance_task_health_report", _raise)

    with app.app_context():
        caplog.set_level("ERROR")
        findings, extra = core_health_panel._compact_task_health(SimpleNamespace(id=1))

    assert extra == {}
    assert len(findings) == 1
    assert _SENTINEL not in findings[0].detail
    assert "okunamadı" in findings[0].detail
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


def test_compact_publish_preflight_failure_is_sanitized(app, monkeypatch, caplog):
    from app.services.performance import core_health_panel

    def _raise(*_args, **_kwargs):
        raise Exception(_SENTINEL)

    monkeypatch.setattr(core_health_panel, "build_publish_preflight_report", _raise)

    with app.app_context():
        caplog.set_level("ERROR")
        findings, extra = core_health_panel._compact_publish_preflight(SimpleNamespace(id=1))

    assert extra == {}
    assert len(findings) == 1
    assert _SENTINEL not in findings[0].detail
    assert "okunamadı" in findings[0].detail
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 5. app/services/settings/foundation_access.py
# ---------------------------------------------------------------------------


def test_ensure_settings_phase1_seeded_handler_failure_returns_safe_error():
    from app.services.settings.foundation_access import ensure_settings_phase1_seeded_handler

    def _raise_flatten():
        raise Exception(_SENTINEL)

    result = ensure_settings_phase1_seeded_handler(
        updated_by_user_id=1,
        table_exists=lambda _name: True,
        flatten_menu_definitions_func=_raise_flatten,
        filter_live_menu_keys=lambda keys: list(keys),
        static_role_default_menu_keys_func=lambda _role: set(),
        role_menu_defaults={},
        role_menu_default_model=None,
        system_setting_model=None,
        module_setting_model=None,
        db_session=SimpleNamespace(rollback=lambda: None),
        system_definitions=[],
        iter_live_module_setting_definitions_func=lambda: [],
        value_to_storage=lambda value, _type: str(value),
        safe_rollback=lambda: None,
    )

    assert result["ok"] is False
    assert _SENTINEL not in str(result.get("error"))
    assert result["error"] == "Ayarlar omurgası hazırlanırken beklenmeyen bir hata oluştu."


# ---------------------------------------------------------------------------
# 6. app/services/ai/preflight.py
# ---------------------------------------------------------------------------


def test_import_symbol_failure_is_sanitized_and_logged(monkeypatch, caplog):
    from app.services.ai import preflight

    def _raise_import(_name):
        raise ModuleNotFoundError(_SENTINEL)

    monkeypatch.setattr(preflight.importlib, "import_module", _raise_import)

    caplog.set_level("ERROR")
    ok, message = preflight._import_symbol("app.some.nonexistent.module")

    assert ok is False
    assert _SENTINEL not in message
    assert message == "Import zinciri şu anda doğrulanamadı."
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 7. app/services/ai_agent/service.py
# ---------------------------------------------------------------------------


def test_ai_agent_full_tutor_fallback_error_note_never_leaks_raw_exception(monkeypatch, caplog):
    from app.services.ai_agent import assistant_full_stepwise_tutor_v5, service

    def _raise_tutor(*_args, **_kwargs):
        raise Exception(_SENTINEL)

    def _raise_previous(*_args, **_kwargs):
        raise Exception(_SENTINEL + "_LEGACY")

    monkeypatch.setattr(assistant_full_stepwise_tutor_v5, "build_bys360_assistant_full_tutor_reply_v5", _raise_tutor)
    monkeypatch.setattr(service, "_BYS360_ASSISTANT_PREV_BUILD_REPLY_FULL_TUTOR_V5", _raise_previous)

    caplog.set_level("ERROR")
    reply = service._legacy_build_ai_agent_reply_fulltutor(SimpleNamespace(id=1, role="personel"), "BYS360'ı nasıl kullanırım?")

    assert reply["ok"] is True
    assert _SENTINEL not in str(reply)
    assert reply["error_note"] == "Asistan geçici olarak güvenli yedek modda çalışıyor."
    assert "BYS360 Asistanı" in reply["answer"]
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# 8. v2_1_2 .. v2_1_6 category-family "quality gate" screens
#    (app/templates/performance/v2_1_{2,3,4,5,6}_*.html render
#    {{ item.message }} / {{ check.message }} for each gate.checks row)
# ---------------------------------------------------------------------------


def test_v2_1_2_category_quality_gate_exception_check_is_sanitized(app, monkeypatch):
    from app.services.performance import v2_1_2_category_quality_gate as gate

    def _raise(*_args, **_kwargs):
        raise Exception(_SENTINEL)

    monkeypatch.setattr(gate, "ensure_category_schema", _raise)

    with app.app_context():
        result = gate.run_v2_1_2_category_quality_gate()

    assert result["ok"] is False
    messages = [c["message"] for c in result["checks"]]
    assert not any(_SENTINEL in m for m in messages)
    assert "Kalite kapısı kontrolü sırasında beklenmeyen bir hata oluştu." in messages


def test_v2_1_3_personnel_category_card_gate_exception_check_is_sanitized(app, monkeypatch):
    from app.services.performance import v2_1_3_personnel_category_card_gate as gate

    def _raise(*_args, **_kwargs):
        raise Exception(_SENTINEL)

    monkeypatch.setattr(gate, "ensure_v2_1_3_schema", _raise)

    with app.app_context():
        result = gate.run_v2_1_3_personnel_category_card_gate()

    assert result["ok"] is False
    messages = [c["message"] for c in result["checks"]]
    assert not any(_SENTINEL in m for m in messages)
    assert "Kalite kapısı kontrolü sırasında beklenmeyen bir hata oluştu." in messages


def test_v2_1_4_category_scope_visibility_gate_exception_check_is_sanitized(app, monkeypatch):
    from app.services.performance import v2_1_4_category_scope_visibility_gate as gate

    def _raise(*_args, **_kwargs):
        raise Exception(_SENTINEL)

    monkeypatch.setattr(gate, "ensure_category_scope_schema", _raise)

    with app.app_context():
        result = gate.run_v2_1_4_category_scope_visibility_gate()

    assert result["ok"] is False
    messages = [c["message"] for c in result["checks"]]
    assert not any(_SENTINEL in m for m in messages)
    assert "Kalite kapısı kontrolü sırasında beklenmeyen bir hata oluştu." in messages


def test_v2_1_5_category_period_scope_gate_exception_check_and_schema_are_sanitized(app, monkeypatch):
    from app.services.performance import v2_1_5_category_period_scope_gate as gate

    def _raise(*_args, **_kwargs):
        raise Exception(_SENTINEL)

    monkeypatch.setattr(gate, "ensure_category_period_scope_schema", _raise)

    with app.app_context():
        result = gate.run_v2_1_5_category_period_scope_gate()

    assert result["ok"] is False
    messages = [c["message"] for c in result["checks"]]
    assert not any(_SENTINEL in m for m in messages)
    assert _SENTINEL not in str(result["schema"].get("error"))
    assert "Kalite kapısı kontrolü sırasında beklenmeyen bir hata oluştu." in messages


def test_v2_1_6_category_period_integration_gate_exception_check_and_schema_are_sanitized(app, monkeypatch):
    from app.services.performance import v2_1_6_category_period_integration_gate as gate

    def _raise(*_args, **_kwargs):
        raise Exception(_SENTINEL)

    monkeypatch.setattr(gate, "ensure_category_period_integration_schema", _raise)

    with app.app_context():
        result = gate.run_v2_1_6_category_period_integration_gate()

    assert result["ok"] is False
    messages = [c["message"] for c in result["checks"]]
    assert not any(_SENTINEL in m for m in messages)
    assert _SENTINEL not in str(result["schema"].get("error"))
    assert "Kalite kapısı kontrolü sırasında beklenmeyen bir hata oluştu." in messages
