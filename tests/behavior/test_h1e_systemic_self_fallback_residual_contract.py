"""BYS360 H1E residual closure -- systemic self-fallback hardening.

A final repo-wide residual scan found the same self-fallback anti-pattern
this whole initiative targets (`X_LABELS.get(key, key.replace("_"," ")
.title())`, or in two cases a bare `X_LABELS.get(key, key)` with no
title-casing at all) repeated independently across ~15 files in
app/services/ai/ and app/services/performance/ -- mostly AI-analytics
report builders and legacy performance-gate/status helpers. Every call
site checked only ever passes a value from a small closed set the
accompanying dict already covers, so these were all currently INERT (no
active raw-value leak with today's real data) -- but each one is a
"negative test" gap: any status/module/severity code added to the
underlying model in the future, without a matching dict entry, would
silently render as raw or title-cased English/slug text instead of a
curated Turkish label, with no error or warning.

All ~20 fixed call sites share the exact same shape: only the FALLBACK
branch changed (from an echo/title-case of the raw key to "Bilinmiyor"),
never the dictionaries themselves or the empty-value branch (several of
these already correctly default to a business-appropriate string like
"Genel", "Bekliyor", "Süreç Devam Ediyor", "Durum Yok" for a missing/empty
key -- those defaults are preserved exactly; only the "we have a value
but don't recognize it" branch changed).

Two sites were investigated and deliberately left unfixed (not silently
skipped):
  - app/services/hr_operations_service.py's _document_label() and
    app/services/hr_operations_enhancements.py's inline `.replace('_',' ')
    .title()` for a document/handover `category` field -- this is the
    SAME admin-extensible document-category catalog H1E-E already
    reviewed and deliberately left with a cosmetic fallback (an
    orphaned-but-recognizable code is more useful than "Bilinmiyor" for
    an admin-managed catalog, not a small closed status enum).
  - app/services/ai/visual_reports.py's "feature_distribution" chart-label
    dict comprehension (`{key: key.replace('_',' ').title() for key in
    feature_counter}`) -- built directly from an open-ended AI-feature
    usage counter's own keys, no underlying X_LABELS dict exists to reuse,
    and inventing a whole new closed taxonomy for internal feature-flag
    identifiers was judged out of proportion to what this residual wave
    was closing.
  - app/services/performance/process_engine_phase6_president_approvals.py:
    325's `_public_status_label(value, fallback="Başkan Onayı Bekliyor")`
    matched the raw grep shape but is NOT actually the anti-pattern -- its
    fallback is a caller-supplied, business-appropriate default parameter,
    not an echo of the raw value. False positive, left untouched.

Writes NOTHING to any production source file -- only imports and calls
pure functions with plain Python values, no DB/app fixture needed for
most of these.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_systemic_self_fallback_tmp" / "test_dbs"


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-systemic-self-fallback-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-systemic-self-fallback-first-login-test-pw")
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


def test_ai_module_report_label_functions_never_leak_raw() -> None:
    from app.services.ai.executive_report_exports import _module_label as exec_module_label
    from app.services.ai.final_live_hardening import _module_label as live_module_label
    from app.services.ai.module_scope import ai_module_label
    from app.services.ai.recommendation_priority import (
        _module_label as rec_module_label,
        _severity_label,
        _status_label as rec_status_label,
    )
    from app.services.ai.visibility_gate import _module_label as vis_module_label, _role_label
    from app.services.ai.visual_reports import _label_module, _label_status

    unmapped = "future_ai_thing_v9"
    assert exec_module_label(unmapped) == "Bilinmiyor"
    assert live_module_label(unmapped) == "Bilinmiyor"
    assert ai_module_label(unmapped) == "Bilinmiyor"
    assert rec_module_label(unmapped) == "Bilinmiyor"
    assert _severity_label(unmapped) == "Bilinmiyor"
    assert rec_status_label(unmapped) == "Bilinmiyor"
    assert vis_module_label(unmapped) == "Bilinmiyor"
    assert _role_label(unmapped) == "Bilinmiyor"
    assert _label_module(unmapped) == "Bilinmiyor"
    assert _label_status(unmapped) == "Bilinmiyor"

    # Empty-value fallbacks must stay exactly as they were before this fix.
    assert live_module_label(None) == "Genel"
    assert ai_module_label(None) == "Genel"


def test_performance_gate_status_label_functions_never_leak_raw(app) -> None:
    from app.services.performance.interim_notes_runtime import NOTE_TYPE_LABELS
    from app.services.performance.low_score_process_service import (
        humanize_low_score_status,
        humanize_process_status,
    )
    from app.services.performance.meeting_development_gate import label_status
    from app.services.performance.phase5_scorecard_ui_policy import translate_status
    from app.services.performance.phase6_low_score_approval_policy import (
        status_label as phase6_status_label,
    )
    from app.services.performance.v2_1_6a_category_ui_cleanup import (
        corporate_gate_label,
        label_status as v2_1_6a_label_status,
    )
    from app.services.performance.v2_1_10_evaluation_live_tracking import (
        status_label as v2_1_10_status_label,
    )
    from app.services.performance.v2_1_14_period_center_real_summary import (
        _status_label as v2_1_14_status_label,
    )
    from app.services.performance.v2_1_rule_engine import status_label as rule_engine_status_label

    unmapped = "future_gate_status_v9"
    assert humanize_process_status(unmapped) == "Bilinmiyor"
    assert humanize_low_score_status(unmapped) == "Bilinmiyor"
    assert label_status(unmapped) == "Bilinmiyor"
    assert translate_status(unmapped) == "Bilinmiyor"
    assert phase6_status_label(unmapped) == "Bilinmiyor"
    assert v2_1_6a_label_status(unmapped) == "Bilinmiyor"
    assert corporate_gate_label(unmapped) == "Bilinmiyor"
    assert v2_1_10_status_label(unmapped) == "Bilinmiyor"
    assert v2_1_14_status_label(unmapped) == "Bilinmiyor"
    # rule_engine_status_label() reads a DB-backed module setting
    # (technical_status_localization_enabled), so it needs an app context.
    with app.app_context():
        assert rule_engine_status_label(unmapped) == "Bilinmiyor"

    # NOTE_TYPE_LABELS.get(raw_type, raw_type) -> NOTE_TYPE_LABELS.get(raw_type)
    # in _row_to_note()'s title fallback chain: confirm the dict itself is
    # unaffected and an unmapped key now yields None (falls through to the
    # next `or` clause) rather than echoing the raw key.
    assert NOTE_TYPE_LABELS.get(unmapped) is None

    # Empty/falsy-value fallbacks must stay exactly as they were before
    # this fix -- only the unmapped-but-present branch changed.
    assert humanize_process_status(None) == "Başkan onayı bekliyor"
    assert humanize_process_status("") == "Başkan onayı bekliyor"
    assert humanize_low_score_status(None) == "Süreç Devam Ediyor"
    assert label_status(None) == "Durum Yok"
    assert translate_status(None) == "Süreç Durumu"
    assert phase6_status_label(None) == "Süreç Durumu"
    assert v2_1_14_status_label(None) == "Bekliyor"


def test_known_status_codes_still_translate_correctly_after_the_fix(app) -> None:
    """Confirming the fallback-only fix didn't accidentally touch the
    known-code dict lookups themselves."""
    from app.services.ai.module_scope import ai_module_label
    from app.services.performance.low_score_process_service import humanize_process_status
    from app.services.performance.meeting_development_gate import label_status
    from app.services.performance.v2_1_rule_engine import status_label as rule_engine_status_label

    assert humanize_process_status("president_pending") == "Başkan onayı bekliyor"
    assert humanize_process_status("first_low_warning") == "Düşük Performans Uyarısı Oluşturuldu"
    # A known module key should still resolve to its real label, not "Bilinmiyor".
    known_module = next(iter(ai_module_label.__globals__["AI_MODULE_LABELS"]), None)
    if known_module:
        assert ai_module_label(known_module) != "Bilinmiyor"
    known_gate_status = next(iter(label_status.__globals__["STATUS_LABELS"]), None)
    if known_gate_status:
        assert label_status(known_gate_status) != "Bilinmiyor"
    known_rule_status = next(iter(rule_engine_status_label.__globals__["STATUS_LABELS"]), None)
    if known_rule_status:
        with app.app_context():
            assert rule_engine_status_label(known_rule_status) != "Bilinmiyor"
