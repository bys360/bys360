"""BYS360 H1E-N2 -- performance / report / archive / category display fixes.

A fresh repo-wide grep audit found six more `X_LABELS.get(raw, raw)` /
`raw.replace("_", " ").title()` self-fallback leaks in the performance,
report, archive and category-scope domains. Each site's FALLBACK branch
only (never the dict itself, never the existing empty/None-value default)
was changed so a genuinely unmapped value can no longer echo raw text to a
user:

  - app/performance/phase10_development_guidance_ui.py's
    normalize_recommendation() built `publication_label` with
    `STATUS_LABELS.get(publication_status, publication_status.replace(
    "_", " ").title())` -- the one field on this row-builder's dict that
    did NOT follow the other six sibling fields' established
    `X_LABELS.get(_safe(...), "<Turkish default label>")` shape. Fixed to
    `STATUS_LABELS.get(publication_status, "Taslak")`, matching
    STATUS_LABELS["draft"] == "Taslak" (publication_status's own existing
    empty-value default is "draft" -- unchanged), exactly mirroring how
    the other six sibling fields pair their _safe() default key with that
    key's own Turkish label as the unmapped-value fallback.
  - app/performance/engagement_feedback_routes.py and
    app/performance/feedback_helpers.py both build a flash/audit summary
    string with `SUMMARY_PRESET_LABELS.get(preset, preset)` -- one shared
    dict (app/services/performance/feedback_executive_summary_service.py),
    imported into both call sites. Both fixed to
    `SUMMARY_PRESET_LABELS.get(preset, "Bilinmiyor")`.
  - app/performance/interim_notes_manager_routes.py's `_notes()` built
    `note_type_label` with a bare `NOTE_LABELS.get(key, key)` (not even
    title-cased). Fixed to `NOTE_LABELS.get(key, "Bilinmiyor")`.
  - app/services/performance/archive_service.py's
    validate_archive_excel_schema() built its "missing Excel headers"
    error message with `readable.get(m, m)`. Investigated: `m` is always
    drawn from `missing = required - set(mapping.values())`, and
    `required` ({"result_year", "period_label", "score"}) is exactly the
    key set of the local `readable` dict -- so `m` can never actually be
    absent from `readable` today; this branch is provably dead code with
    the current constants. Hardened anyway to `readable.get(m,
    "Bilinmiyor")` for defense-in-depth (in case `required` ever grows
    without a matching `readable` entry), matching the fix standard. This
    is unrelated to the deliberately-untouched `unknown` list a few lines
    below, which intentionally echoes a user's own free-form uploaded
    column header text back to them (genuinely open-ended user input, not
    a small closed machine-code set) so they can find and fix it in their
    file.
  - app/services/performance/v2_1_4_category_scope_visibility.py's
    upsert_category_scope_draft() built the scope draft's display name
    with `categories.get(key, key)`. By the time this runs, `key` is
    forced to "diger" whenever the caller's category_key wasn't found in
    the live `categories` map -- but if that map itself came back without
    a "diger" entry (e.g. seeding hasn't completed yet), the raw machine
    slug "diger" would have leaked into a human-facing scope name. Fixed
    to `categories.get(key, "Diğer")`.
  - app/services/performance_dashboard_live_service.py's
    _category_averages() built each category bucket's chart label with
    `CATEGORY_SHORT_LABEL.get(category, category)`, where `category`
    iterates CATEGORY_ORDER -- today a fixed 6-entry list fully covered by
    CATEGORY_SHORT_LABEL, so also currently inert, but the same
    "taxonomy grows without a matching label" risk as the systemic
    self-fallback residual wave. Fixed to
    `CATEGORY_SHORT_LABEL.get(category, "Diğer")`, consistent with this
    same file's existing `category = category or "Diğer"` catch-all
    bucket a few lines above it.

Also found in passing but NOT fixed (out of this wave's explicit scope,
flagged for the coordinator): app/services/performance/
feedback_audit_service.py:105's `_status_label()` has the identical
`labels.get(raw, raw or "-")` self-fallback anti-pattern this whole H1E
initiative targets -- an unmapped, non-empty feedback/meeting status code
would still echo raw into audit-dashboard timelines. Left untouched since
it wasn't one of this wave's six named findings.

Writes to a real temporary SQLite DB via the app fixture (interim notes,
category-scope-draft and feedback-digest-audit tests); the other three
are pure-function/direct-argument tests needing no DB.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_n2_perf_report_archive_category_tmp" / "test_dbs"
_PASSWORD = "H1EN2PerfReportArchiveCategoryTest1!"


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-n2-perf-report-archive-category-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-n2-perf-report-archive-category-first-login-test-pw")
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


def _create_user(app, *, sicil_no, role="personel", password=_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="H1EN2",
            soyad="PerfReportArchiveCategoryContract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


# ---------------------------------------------------------------------------
# 1: app/performance/phase10_development_guidance_ui.py -- normalize_recommendation()
# ---------------------------------------------------------------------------


def test_publication_label_never_leaks_raw_and_known_value_still_correct() -> None:
    from app.performance.phase10_development_guidance_ui import normalize_recommendation

    known = normalize_recommendation({"publication_status": "published"})
    assert known["publication_label"] == "Yayınlandı"
    assert known["publication_status"] == "published"  # raw stored value untouched

    unmapped = normalize_recommendation({"publication_status": "future_status_v99"})
    assert unmapped["publication_label"] == "Taslak"
    assert unmapped["publication_label"] != "future_status_v99"
    assert unmapped["publication_label"] != "Future Status V99"
    # the raw value itself must still pass through unmodified in the
    # non-label field -- only the *_label field's fallback changed.
    assert unmapped["publication_status"] == "future_status_v99"

    # empty/None-value default branch (_safe(..., "draft")) is untouched.
    empty = normalize_recommendation({})
    assert empty["publication_status"] == "draft"
    assert empty["publication_label"] == "Taslak"


# ---------------------------------------------------------------------------
# 2 & 3: SUMMARY_PRESET_LABELS shared dict -- engagement_feedback_routes.py's
# flash message and feedback_helpers.py's _record_feedback_digest_audit().
# ---------------------------------------------------------------------------


def test_feedback_digest_audit_summary_never_leaks_raw_preset(app) -> None:
    """_record_feedback_digest_audit() itself performs no preset validation
    (unlike its only current caller), so it is the direct, always-reachable
    real-behavior proof for the shared SUMMARY_PRESET_LABELS.get(preset, ...)
    fallback used identically at both fixed call sites."""
    from app.extensions import db
    from app.models import AuditLog
    from app.performance.feedback_helpers import _record_feedback_digest_audit

    with app.app_context():
        # _record_feedback_digest_audit() doesn't propagate
        # record_feedback_audit_event()'s bool return value (a pre-existing,
        # unrelated quirk -- its own signature is `-> None`), so success is
        # verified here by reading the row back rather than by a return value.
        _record_feedback_digest_audit(
            source_id=101,
            preset="future_preset_v99",
            actor_user_id=None,
            recipient_count=3,
            mail_success_count=2,
        )
        db.session.commit()
        entry = AuditLog.query.filter_by(entity_id=101, action="feedback_digest_sent").first()
        assert entry is not None
        assert "Bilinmiyor" in entry.summary
        assert "future_preset_v99" not in entry.summary
        # the raw preset value must still be preserved, unchanged, in the
        # machine-readable audit payload -- only the human-facing summary
        # text's fallback changed.
        assert '"preset": "future_preset_v99"' in entry.new_data_json

        _record_feedback_digest_audit(
            source_id=102,
            preset="daily",
            actor_user_id=None,
            recipient_count=1,
            mail_success_count=1,
        )
        db.session.commit()
        entry2 = AuditLog.query.filter_by(entity_id=102, action="feedback_digest_sent").first()
        assert entry2 is not None
        assert "Günlük" in entry2.summary


def test_feedback_executive_summary_run_digest_flash_shows_known_preset_label(app, monkeypatch) -> None:
    """Route/behavior-level check: calls the REAL undecorated view function
    (login_required/menu_key_required unwrapped via functools.wraps'
    __wrapped__ chain, so real permission-map/session plumbing isn't
    needed) with only its heavy, unrelated collaborators (scope
    resolution, mail/notification dispatch, audit write) stubbed out, and
    asserts the real flash() call -- using the exact fixed f-string --
    shows the Turkish preset label.

    NOTE: this route normalizes `preset` to "daily" whenever it isn't a
    SUMMARY_PRESET_LABELS key *before* reaching the fixed line (see
    `if preset not in SUMMARY_PRESET_LABELS: preset = "daily"` a few lines
    above it) -- so, unlike _record_feedback_digest_audit() above, this
    call site's fallback branch is unreachable through the real route.
    Both call sites share the one SUMMARY_PRESET_LABELS dict and the
    identical `.get(preset, "Bilinmiyor")` shape, so the sibling test
    above is what actually proves the unmapped-value behavior for this
    fix; this test only proves the known-value path still renders
    correctly end-to-end through the real view function's flash() call.
    """
    from flask import get_flashed_messages
    from flask_login import login_user

    import app.performance.engagement_feedback_routes as efr
    from app.extensions import db
    from app.models import User

    user_id = _create_user(app, sicil_no="h1e_n2_feedback_digest_actor", role="admin")

    def _fake_scope_context(scope_value=""):
        return {"scope_label": "Tümü", "role_title": "Yönetici"}, "all", []

    def _fake_load_scoped(selected_scope, scope_employee_ids):
        return [], []

    def _fake_dispatch(*args, **kwargs):
        return {
            "source_id": 1,
            "notification_sent": 0,
            "notification_skipped": 0,
            "mail_success_count": 0,
            "recipient_count": 0,
            "mail_failed_count": 0,
        }

    def _fake_record_audit(**kwargs):
        return True

    monkeypatch.setattr(efr, "_get_scope_context", _fake_scope_context)
    monkeypatch.setattr(efr, "_load_scoped_feedback_data", _fake_load_scoped)
    monkeypatch.setattr(efr, "dispatch_feedback_executive_summary", _fake_dispatch)
    monkeypatch.setattr(efr, "_record_feedback_digest_audit", _fake_record_audit)

    raw_view = efr.feedback_executive_summary_run_digest.__wrapped__.__wrapped__

    with app.test_request_context(
        "/performance/feedback-executive-summary/run-digest",
        method="POST",
        data={"preset": "daily"},
    ):
        user = db.session.get(User, user_id)
        login_user(user)
        raw_view()
        messages: list[tuple[str, str]] = get_flashed_messages(with_categories=True)  # type: ignore[assignment]

    joined = " | ".join(msg for _category, msg in messages)
    assert "Günlük yönetici özeti çalıştırıldı." in joined
    assert "daily yönetici özeti" not in joined


# ---------------------------------------------------------------------------
# 4: app/performance/interim_notes_manager_routes.py -- _notes()
# ---------------------------------------------------------------------------


def test_interim_notes_note_type_label_never_leaks_raw(app) -> None:
    from sqlalchemy import text

    from app.extensions import db
    from app.performance.interim_notes_manager_routes import _cols, _notes

    employee_id = _create_user(app, sicil_no="h1e_n2_interim_notes_employee")

    with app.app_context():
        db.session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS performance_interim_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER,
                    period_id INTEGER,
                    note_type VARCHAR(40),
                    title VARCHAR(180),
                    note_text TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1
                )
                """
            )
        )
        db.session.execute(
            text(
                """
                INSERT INTO performance_interim_notes
                    (employee_id, period_id, note_type, note_text, is_active)
                VALUES
                    (:emp, NULL, 'olumlu_olay', 'Bilinen not tipi', 1),
                    (:emp, NULL, 'future_note_type_v99', 'Bilinmeyen not tipi', 1)
                """
            ),
            {"emp": employee_id},
        )
        db.session.commit()

        # _cols() is lru_cached by table name; earlier tests in this same
        # process may have cached a stale (or empty) column set for this
        # table before we created it here, so clear the cache to force a
        # fresh PRAGMA table_info() introspection against our real table.
        _cols.cache_clear()

        notes = _notes([{"id": employee_id}], employee_id=employee_id)

    by_type = {n["note_type"]: n for n in notes}
    assert set(by_type) == {"olumlu_olay", "future_note_type_v99"}

    assert by_type["olumlu_olay"]["note_type_label"] == "Olumlu Olay"

    assert by_type["future_note_type_v99"]["note_type_label"] == "Bilinmiyor"
    assert by_type["future_note_type_v99"]["note_type_label"] != "future_note_type_v99"
    # the raw stored note_type value itself must be untouched.
    assert by_type["future_note_type_v99"]["note_type"] == "future_note_type_v99"


# ---------------------------------------------------------------------------
# 5: app/services/performance/archive_service.py -- validate_archive_excel_schema()
# ---------------------------------------------------------------------------


def test_archive_excel_missing_headers_error_uses_turkish_labels_not_raw_keys() -> None:
    """`readable.get(m, m)`'s fallback is provably dead code with today's
    constants: `missing` can only ever contain members of `required`
    ({"result_year", "period_label", "score"}), and `readable`'s keys are
    exactly that same set -- so `m` can never actually be absent from
    `readable`. This test proves the reachable (known-key) path renders
    the Turkish labels, not the internal canonical machine keys, and
    that the deliberately-left-raw `unknown` headers warning (a
    genuinely different, free-form-user-input code path) is unaffected."""
    from app.services.performance.archive_service import validate_archive_excel_schema

    result = validate_archive_excel_schema(["Personel", "Puan", "Rastgele Sütun"])

    assert result["ok"] is False
    joined_errors = " | ".join(result["errors"])
    assert "Yıl" in joined_errors
    assert "Dönem" in joined_errors
    assert "result_year" not in joined_errors
    assert "period_label" not in joined_errors

    # the genuinely free-form, user-uploaded unrecognized header must still
    # be shown raw (untouched, intentional) so the user can locate it.
    joined_warnings = " | ".join(result["warnings"])
    assert "Rastgele Sütun" in joined_warnings


# ---------------------------------------------------------------------------
# 6: app/services/performance/v2_1_4_category_scope_visibility.py --
#    upsert_category_scope_draft()
# ---------------------------------------------------------------------------


def test_upsert_category_scope_draft_name_never_leaks_raw_category_key(app, monkeypatch) -> None:
    import app.services.performance.v2_1_4_category_scope_visibility as v214

    with app.app_context():
        known = v214.upsert_category_scope_draft(category_key="guvenlik")
        assert known["scope_name"] == "Güvenlik Kategori Kapsamı"
        assert known["category_key"] == "guvenlik"  # raw machine key column untouched

        # Simulate the defended-against edge case: the live categories map
        # (e.g. before seeding has completed) doesn't contain the
        # "diger" catch-all key that `key` gets forced to for any
        # unrecognized category_key.
        monkeypatch.setattr(v214, "list_categories", lambda include_inactive=False: [])

        unmapped = v214.upsert_category_scope_draft(category_key="totally_unknown_key_v99")
        assert unmapped["scope_name"] == "Diğer Kategori Kapsamı"
        assert unmapped["scope_name"] != "diger Kategori Kapsamı"
        # the raw canonical machine key (forced to "diger") is still what
        # gets stored in the category_key column -- only the human-facing
        # scope_name's fallback text changed.
        assert unmapped["category_key"] == "diger"


# ---------------------------------------------------------------------------
# 7: app/services/performance_dashboard_live_service.py -- _category_averages()
# ---------------------------------------------------------------------------


def test_category_averages_label_never_leaks_raw_category(app, monkeypatch) -> None:
    import app.services.performance_dashboard_live_service as pdls

    monkeypatch.setattr(pdls, "CATEGORY_ORDER", [*pdls.CATEGORY_ORDER, "future_category_v99"])

    with app.app_context():
        result = pdls._category_averages(None, [])

    by_full_label = {row["full_label"]: row for row in result}
    assert set(by_full_label) == {*pdls.CATEGORY_SHORT_LABEL, "future_category_v99"}

    assert by_full_label["Güvenlik"]["label"] == "Güvenlik"
    assert by_full_label["future_category_v99"]["label"] == "Diğer"
    assert by_full_label["future_category_v99"]["label"] != "future_category_v99"
    # full_label -- the raw/underlying category value -- must be untouched.
    assert by_full_label["future_category_v99"]["full_label"] == "future_category_v99"
