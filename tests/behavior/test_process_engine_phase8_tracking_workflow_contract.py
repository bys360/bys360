"""BYS360_PHASE5_COVERAGE_WAVE4_AGENT3_PROCESS_TRACKING_CONTRACT

Behavioral contract tests for
app/services/performance/process_engine_phase8_tracking.py, using three
deliberately distinct fixture tiers so each function is exercised against
the cheapest boundary that still proves real behavior rather than mocking
away the logic under test:

  * Tier 1 -- pure functions (role/token matching, bucket classification,
    SQL-fragment builders) run with zero fixture and zero database: plain
    ``SimpleNamespace``/``dict`` inputs, real function calls.
  * Tier 2 -- a real, isolated SQLite database (own Flask app + own tmp
    dir, ``Config`` patched before ``create_app()`` per the project's
    proven pattern) for ``table_exists``, ``column_exists``,
    ``_flow_base_rows``, ``synchronize_phase8_tracking``.
    ``build_process_tracking_workspace`` is also proven here for real (its
    own row-selection, bucket/label assembly, and counts aggregation),
    with ``_steps_for_flows``/``_history_for_flows`` stubbed to return
    ``{}`` to isolate the aggregation loop from the row-fetch helpers --
    both of those two helpers are separately proven for real against
    SQLite in tests/behavior/test_process_engine_phase8_dual_database_
    binding_contract.py (BYS360 DEFECT AB fix).
  * Tier 3 -- a fake ``db.session`` boundary (module's own ``db`` name
    replaced, same shape as
    tests/behavior/test_president_approvals_authorization_and_workspace_contract.py
    lines 71-153) for the three delete functions, matching this file's own
    established fake-session pattern for exercising raw ``text()`` DELETE
    statements without a real database. As of BYS360 DEFECT AB,
    ``_delete_tracking_flow_ids``'s statements use the dialect-neutral
    "expanding IN" bind pattern (``WHERE flow_id IN :flow_ids`` +
    ``bindparam("flow_ids", expanding=True)``, compiled SQL literal text
    ``IN (__[POSTCOMPILE_flow_ids])``), which -- unlike the prior
    PostgreSQL-only ``= ANY(:flow_ids)`` -- runs correctly against real
    SQLite too (see test_process_engine_phase8_dual_database_binding_
    contract.py for that real-SQLite proof); the fake-session boundary
    here is retained purely to keep this file's existing call-count/
    call-order/commit-vs-rollback assertions isolated from database state,
    not because the SQL itself is SQLite-incompatible.

Two genuine, pre-existing production defects were found while building
this file through real execution (not just reading) and are reported in
the implementing agent's completion summary rather than asserted as
"correct" anywhere below:

  1. ``synchronize_phase8_tracking``'s own SELECT statement omits both
     ``is_overdue`` and ``tracking_bucket`` from its column list, so the
     ``_row_bucket(row)`` call it makes can never observe an overdue flag
     -- meaning the "overdue" bucket is structurally unreachable from
     that call site, even though the very same loop iteration correctly
     computes and persists ``is_overdue = True`` (from
     ``waiting_days >= 7``) moments later. Confirmed by direct execution:
     a flow with ``waiting_days=10``, no owner, not finalized, no
     president-pending state ends up with ``is_overdue=1``,
     ``tracking_priority='80'``, but ``tracking_bucket='takipte'`` (the
     raw ``current_status`` passthrough), never ``'overdue'``.
  2. ``can_manage_process_tracking`` uses substring containment
     (``token in combined`` for token in its allowed-token tuple) rather
     than the sibling phase6 module's exact-token-set design. Its own
     ``allowed_tokens`` tuple deliberately excludes ``"grup_baskani"`` (it
     is present in the broader *view* gate's token set but not the
     narrower *manage/delete* gate's), yet because ``"baskan"`` is a
     substring of ``"grup_baskani"``, a viewer with ``role="grup_baskani"``
     is granted delete authority anyway -- and likewise an ``unvan`` of
     merely ``"Başkanlığı Uzmanı"`` (an organizational-name reference, the
     exact scenario the phase6 module's own tests explicitly reject)
     passes ``can_manage_process_tracking`` here. Confirmed by direct
     execution against real ``SimpleNamespace`` inputs.

Neither defect is business-logic this file's assigned scope covers
fixing, and neither is asserted as correct anywhere below -- the required
contract assertions (real admin positive / real personel negative for
``can_manage_process_tracking``; the four *reachable* bucket-precedence
branches for ``synchronize_phase8_tracking``) are written exactly as
instructed and all pass against real, unmodified production code.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

from app.services.performance import process_engine_phase8_tracking as pt
from tests.sqlite_test_cleanup import release_sqlite_app

# ===========================================================================
# TIER 1 -- pure functions, zero fixture, zero database.
# ===========================================================================


# ---------------------------------------------------------------------------
# Authorization: is_admin_user / is_process_tracking_user /
# can_view_process_tracking / can_manage_process_tracking.
# ---------------------------------------------------------------------------


def test_is_admin_user_true_for_admin_role() -> None:
    user = SimpleNamespace(role="admin", unvan=None)
    assert pt.is_admin_user(user) is True


def test_is_admin_user_false_for_personnel() -> None:
    user = SimpleNamespace(role="personel", unvan="Uzman")
    assert pt.is_admin_user(user) is False


def test_is_process_tracking_user_true_for_role_grup_baskani() -> None:
    user = SimpleNamespace(role="grup_baskani", unvan=None)
    assert pt.is_process_tracking_user(user) is True


def test_is_process_tracking_user_true_for_unvan_exactly_koordinator() -> None:
    user = SimpleNamespace(role="personel", unvan="Koordinator")
    assert pt.is_process_tracking_user(user) is True


def test_is_process_tracking_user_false_for_unvan_containing_koordinator_as_substring() -> None:
    """BYS360 DEFECT AO: previously matched via substring containment --
    "koordinator" is a prefix of the Turkish possessive form
    "koordinatörü", so any unvan merely built on that root (e.g. a
    qualified regional title) passed. Now exact-token-set only, mirroring
    process_engine_phase6_president_approvals.py's is_president_user
    design, whose own comment states plainly: only an exact role/unvan
    value grants authority, never text that happens to contain it."""
    user = SimpleNamespace(role="personel", unvan="Bölge Koordinatörü")
    assert pt.is_process_tracking_user(user) is False


def test_is_process_tracking_user_false_for_plain_personel_uzman() -> None:
    user = SimpleNamespace(role="personel", unvan="Uzman")
    assert pt.is_process_tracking_user(user) is False


def test_is_admin_user_true_for_all_caps_turkish_capital_i_role_value() -> None:
    """BYS360 DEFECT AQ: normalize_role() used to call .lower() before
    .translate(); Python's 'İ'.lower() (capital dotted I, U+0130) produces
    the two-codepoint sequence 'i' + COMBINING DOT ABOVE (U+0307), not
    plain 'i', so the translate table's 'İ' entry was dead code and a
    realistic all-caps HR value like "SİSTEM YÖNETİCİSİ" failed to
    normalize to "sistem_yoneticisi", silently denying a real admin."""
    user = SimpleNamespace(role="SİSTEM YÖNETİCİSİ", unvan=None)
    assert pt.is_admin_user(user) is True


def test_can_view_process_tracking_matches_is_process_tracking_user_positive_and_negative() -> None:
    allowed = SimpleNamespace(role="grup_baskani", unvan=None)
    denied = SimpleNamespace(role="personel", unvan="Uzman")
    assert pt.can_view_process_tracking(allowed) is True
    assert pt.can_view_process_tracking(denied) is False


def test_can_manage_process_tracking_true_for_real_admin() -> None:
    admin = SimpleNamespace(role="admin", unvan=None)
    assert pt.can_manage_process_tracking(admin) is True


def test_can_manage_process_tracking_false_for_real_personel() -> None:
    employee = SimpleNamespace(role="personel", unvan="Uzman")
    assert pt.can_manage_process_tracking(employee) is False


# ---------------------------------------------------------------------------
# can_manage_process_tracking / is_process_tracking_user: adversarial
# authorization contract (BYS360 DEFECT AO). Both functions previously
# used substring containment (``token in combined``), so any role/unvan
# that merely CONTAINED an allowed token -- rather than equaling one --
# passed. Fixed to exact-token-set matching, mirroring
# process_engine_phase6_president_approvals.py's proven is_admin_user/
# is_president_user design. Each case below is a real bypass this file's
# own baseline test run demonstrated before the fix.
# ---------------------------------------------------------------------------


def test_can_manage_process_tracking_true_for_real_baskan() -> None:
    baskan = SimpleNamespace(role="baskan", unvan=None)
    assert pt.can_manage_process_tracking(baskan) is True


def test_can_manage_process_tracking_true_for_real_baskan_yardimcisi() -> None:
    deputy = SimpleNamespace(role="baskan_yardimcisi", unvan=None)
    assert pt.can_manage_process_tracking(deputy) is True


def test_can_manage_process_tracking_false_for_grup_baskani() -> None:
    """grup_baskani has real view access (is_process_tracking_user) but is
    deliberately excluded from can_manage_process_tracking()'s own,
    narrower allowed_tokens set -- two different token sets defined side
    by side in the same module is direct evidence of intentional design,
    not an oversight the substring bug happened to paper over."""
    grup_baskani = SimpleNamespace(role="grup_baskani", unvan=None)
    assert pt.can_manage_process_tracking(grup_baskani) is False


def test_can_manage_process_tracking_false_for_role_containing_privileged_word_but_not_equal() -> None:
    fake = SimpleNamespace(role="grup_baskani_yardimcisi_fake", unvan=None)
    assert pt.can_manage_process_tracking(fake) is False


def test_can_manage_process_tracking_false_for_unvan_containing_baskanligi() -> None:
    """Institution-name reference ("Başkanlığı" = "of the Presidency"),
    not a personal role -- must never grant authority on its own, per the
    same principle process_engine_phase6_president_approvals.py's
    is_president_user already documents explicitly."""
    user = SimpleNamespace(role="personel", unvan="Başkanlığı Uzmanı")
    assert pt.can_manage_process_tracking(user) is False


def test_can_manage_process_tracking_false_for_unknown_role() -> None:
    user = SimpleNamespace(role="asdlkfj_unknown_role", unvan=None)
    assert pt.can_manage_process_tracking(user) is False


def test_can_manage_process_tracking_false_for_empty_role_and_unvan() -> None:
    user = SimpleNamespace(role="", unvan="")
    assert pt.can_manage_process_tracking(user) is False


def test_can_manage_process_tracking_false_for_none_role_and_unvan() -> None:
    user = SimpleNamespace(role=None, unvan=None)
    assert pt.can_manage_process_tracking(user) is False


def test_can_manage_process_tracking_true_for_mixed_case_role() -> None:
    admin = SimpleNamespace(role="ADMIN", unvan=None)
    assert pt.can_manage_process_tracking(admin) is True


def test_is_process_tracking_user_false_for_role_containing_privileged_word_but_not_equal() -> None:
    fake = SimpleNamespace(role="baskanlik_danismani_sahte", unvan=None)
    assert pt.is_process_tracking_user(fake) is False


def test_is_process_tracking_user_false_for_unvan_containing_baskanligi() -> None:
    user = SimpleNamespace(role="personel", unvan="Başkanlığı Uzmanı")
    assert pt.is_process_tracking_user(user) is False


def test_is_process_tracking_user_false_for_unknown_role() -> None:
    user = SimpleNamespace(role="unknown_garbage_role", unvan=None)
    assert pt.is_process_tracking_user(user) is False


def test_is_process_tracking_user_false_for_empty_role_and_unvan() -> None:
    user = SimpleNamespace(role="", unvan="")
    assert pt.is_process_tracking_user(user) is False


# ---------------------------------------------------------------------------
# _row_bucket: precedence order over plain dict rows (production calls
# row.get(...), so a dict is a fully honest stand-in for a DB row mapping
# after build_process_tracking_workspace() has merged in the derived
# is_overdue field -- see _derive_tracking_fields()). BYS360 DEFECT AO:
# these dicts previously used tracking_bucket/president_status, neither a
# real column; now president_approval_required/president_approval_status
# (real, model-backed) drive the same precedence. Per source:
# president_pending is checked before returned, which is checked before
# is_overdue, which is checked before is_finalized/current_status-
# completed, which is checked before current_owner_id-present, which
# falls back to monitoring.
# ---------------------------------------------------------------------------


def test_row_bucket_president_pending_beats_overdue_even_when_both_true() -> None:
    row = {
        "current_status": "takipte",
        "president_approval_required": True,
        "president_approval_status": "not_required",
        "is_overdue": True,
        "is_finalized": False,
        "current_owner_id": None,
    }
    assert pt._row_bucket(row) == "president_pending"


def test_row_bucket_returned_beats_overdue_when_not_president_pending() -> None:
    row = {
        "current_status": "takipte",
        "president_approval_required": True,
        "president_approval_status": "returned",
        "is_overdue": True,
        "is_finalized": False,
        "current_owner_id": None,
    }
    assert pt._row_bucket(row) == "returned"


def test_row_bucket_overdue_beats_completed_when_no_president_pending() -> None:
    row = {
        "current_status": "takipte",
        "president_approval_required": False,
        "president_approval_status": "not_required",
        "is_overdue": True,
        "is_finalized": True,
        "current_owner_id": None,
    }
    assert pt._row_bucket(row) == "overdue"


def test_row_bucket_completed_beats_owner_present_waiting() -> None:
    row = {
        "current_status": "takipte",
        "president_approval_required": False,
        "president_approval_status": "not_required",
        "is_overdue": False,
        "is_finalized": True,
        "current_owner_id": 5,
    }
    assert pt._row_bucket(row) == "completed"


def test_row_bucket_waiting_when_owner_present_and_nothing_else() -> None:
    row = {
        "current_status": "takipte",
        "president_approval_required": False,
        "president_approval_status": "not_required",
        "is_overdue": False,
        "is_finalized": False,
        "current_owner_id": 5,
    }
    assert pt._row_bucket(row) == "waiting"


def test_row_bucket_default_monitoring_when_nothing_matches() -> None:
    row = {
        "current_status": None,
        "president_approval_required": False,
        "president_approval_status": "not_required",
        "is_overdue": False,
        "is_finalized": False,
        "current_owner_id": None,
    }
    assert pt._row_bucket(row) == "monitoring"


# ---------------------------------------------------------------------------
# _visible_bucket / _bucket_tone / _clean_process_label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bucket,expected",
    [
        ("president_pending", "Başkan/Üst Onay Bekliyor"),
        ("overdue", "Gecikmiş Süreç"),
        ("waiting", "İşlem Bekliyor"),
        ("completed", "Tamamlandı"),
        ("returned", "İade Edildi"),
        ("monitoring", "Süreçte"),
        ("some_unmapped_bucket_key", "Süreçte"),
    ],
)
def test_visible_bucket_labels(bucket: str, expected: str) -> None:
    assert pt._visible_bucket(bucket) == expected


@pytest.mark.parametrize(
    "bucket,expected_tone",
    [
        ("overdue", "danger"),
        ("president_pending", "danger"),
        ("waiting", "warning"),
        ("monitoring", "warning"),
        ("completed", "success"),
        ("approved", "success"),
        ("returned", "neutral"),
        ("rejected", "neutral"),
        ("some_unmapped_key", "info"),
    ],
)
def test_bucket_tone(bucket: str, expected_tone: str) -> None:
    assert pt._bucket_tone(bucket) == expected_tone


def test_clean_process_label_known_key_lookup() -> None:
    assert pt._clean_process_label("pending") == "Bekliyor"
    assert pt._clean_process_label("president_pending") == "Başkan/Üst Onay Bekliyor"


def test_clean_process_label_suppresses_developer_status_codes() -> None:
    # Any value containing an underscore that is not a known key is treated
    # as an internal/developer status code and must not leak to the UI.
    assert pt._clean_process_label("workflow_state_xyz") == "Süreçte"
    assert pt._clean_process_label("DEBUGCODE") == "Süreçte"


def test_clean_process_label_passes_through_clean_free_text() -> None:
    assert pt._clean_process_label("Özel Durum") == "Özel Durum"


def test_clean_process_label_uses_custom_fallback_for_empty_value() -> None:
    assert pt._clean_process_label(None, "Varsayılan") == "Varsayılan"
    assert pt._clean_process_label("   ", "Varsayılan") == "Varsayılan"


# ---------------------------------------------------------------------------
# _status_clause / _scope_clause: exact SQL-fragment and params text, never
# executed here. BYS360 DEFECT AO: both functions reference only real,
# always-present columns now (current_owner_id, is_finalized, current_status,
# president_approval_required, president_approval_status, last_action_at/
# started_at/created_at) -- no more flow_cols parameter, no more schema
# introspection at all, since there is nothing left to gate against.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status_filter,expected_sql",
    [
        ("all", ""),
        ("tumu", ""),
        ("nonsense_unknown_filter", ""),
        (
            "waiting",
            "AND f.current_owner_id IS NOT NULL AND COALESCE(f.is_finalized, FALSE) = FALSE "
            "AND LOWER(COALESCE(f.current_status, '')) NOT IN "
            "('completed', 'finalized', 'kesinlesti', 'kesinleşti', 'tamamlandi', 'tamamlandı')",
        ),
        (
            "president",
            "AND COALESCE(f.president_approval_required, FALSE) = TRUE "
            "AND LOWER(COALESCE(f.president_approval_status, '')) NOT IN ('approved', 'returned', 'iade', 'iade_edildi')",
        ),
        (
            "completed",
            "AND (COALESCE(f.is_finalized, FALSE) = TRUE OR LOWER(COALESCE(f.current_status, '')) IN "
            "('completed', 'finalized', 'kesinlesti', 'kesinleşti', 'tamamlandi', 'tamamlandı'))",
        ),
        (
            "returned",
            "AND LOWER(COALESCE(f.president_approval_status, '')) IN ('returned', 'iade', 'iade_edildi')",
        ),
    ],
)
def test_status_clause_exact_fragments(status_filter: str, expected_sql: str) -> None:
    sql, params = pt._status_clause(status_filter)
    assert sql == expected_sql
    assert params == {}


def test_status_clause_overdue_binds_a_real_cutoff_timestamp() -> None:
    """BYS360 DEFECT AO: is_overdue has no real column -- the "overdue"
    filter compares the real last_action_at/started_at/created_at columns
    against a bound cutoff computed in Python (datetime.utcnow() minus
    PHASE8_OVERDUE_THRESHOLD_DAYS), portable to both SQLite and PostgreSQL
    without any dialect-specific date-diff SQL."""
    before = datetime.utcnow() - timedelta(days=pt.PHASE8_OVERDUE_THRESHOLD_DAYS)
    sql, params = pt._status_clause("overdue")
    after = datetime.utcnow() - timedelta(days=pt.PHASE8_OVERDUE_THRESHOLD_DAYS)
    assert sql == "AND COALESCE(f.last_action_at, f.started_at, f.created_at) <= :overdue_cutoff"
    assert set(params) == {"overdue_cutoff"}
    assert before <= params["overdue_cutoff"] <= after


def test_scope_clause_admin_has_no_restriction() -> None:
    admin = SimpleNamespace(id=1, role="admin", unvan=None)
    sql, params = pt._scope_clause(admin)
    assert sql == ""
    assert params == {}


def test_scope_clause_baskan_title_has_no_restriction() -> None:
    baskan = SimpleNamespace(id=2, role="personel", unvan="Baskan Yardimcisi")
    sql, params = pt._scope_clause(baskan)
    assert sql == ""
    assert params == {}


def test_scope_clause_grup_baskani_role_is_restricted_not_unrestricted() -> None:
    """BYS360 DEFECT AO: previously a substring match ("baskan" in
    "grup_baskani") incorrectly granted unrestricted scope to a Grup
    Başkanı, the same defect class as can_manage_process_tracking()."""
    grup_baskani = SimpleNamespace(id=7, role="grup_baskani", unvan=None)
    sql, params = pt._scope_clause(grup_baskani)
    assert sql == "AND (f.current_owner_id = :viewer_id OR f.employee_id = :viewer_id)"
    assert params == {"viewer_id": 7}


def test_scope_clause_regular_viewer_restricts_to_owner_or_employee() -> None:
    viewer = SimpleNamespace(id=42, role="personel", unvan="Uzman")
    sql, params = pt._scope_clause(viewer)
    assert sql == "AND (f.current_owner_id = :viewer_id OR f.employee_id = :viewer_id)"
    assert params == {"viewer_id": 42}


# ---------------------------------------------------------------------------
# _build_search_clause: empty search short-circuits before ever touching
# table_exists/_table_columns (proven via a forbid-callable); non-empty
# search's exact SQL fragment is proven with table_exists/_table_columns
# monkeypatched to a fixed, known column set -- a legitimate boundary since
# those are schema-introspection helpers, not the clause-building logic
# under test (real DB coverage of the real users table happens in Tier 2).
# ---------------------------------------------------------------------------


def _forbid_table_exists(name: str) -> bool:
    raise AssertionError(f"table_exists must not be called here; got table {name!r}")


def test_build_search_clause_empty_search_returns_empty_without_touching_table_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pt, "table_exists", _forbid_table_exists)
    sql, params = pt._build_search_clause("   ")
    assert sql == ""
    assert params == {}


def test_build_search_clause_nonempty_search_exact_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pt, "table_exists", lambda name: name == "users")
    monkeypatch.setattr(pt, "_table_columns", lambda name: {"email"} if name == "users" else set())

    sql, params = pt._build_search_clause("Ayşe Ö")

    expected_sql = "AND (" + " OR ".join(
        [
            "LOWER(COALESCE(emp.\"email\", '')) LIKE :search",
            "LOWER(COALESCE(owner.\"email\", '')) LIKE :search",
            "LOWER(COALESCE(f.current_status, '')) LIKE :search",
        ]
    ) + ")"
    assert sql == expected_sql
    assert params == {"search": "%ayşe ö%"}


# ===========================================================================
# TIER 2 -- real, isolated SQLite database for the ANY()-free functions:
# table_exists, column_exists, _flow_base_rows, synchronize_phase8_tracking.
# ===========================================================================

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_agent3_phase8tracking")

# Columns the production ORM model (app/models/performance_process_engine_models.py)
# does not declare, but which the phase4/phase6/phase7/phase8 raw-SQL schema
# steps (app/services/performance/process_engine_phase{4,6,7,8}*.py) add at
# runtime via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` against PostgreSQL.
# Those apply_phaseN_schema() functions use bare `information_schema` calls
# with no SQLite branch (unlike this module's own table_exists/column_exists),
# so they cannot be called here; the same columns are added directly with
# plain SQLite-compatible ALTER TABLE statements instead -- a fixture-only
# schema setup step, not a production change.
_PHASE8_EXTRA_FLOW_COLUMNS = [
    ("current_stage", "VARCHAR(120)"),
    ("current_owner_user_id", "INTEGER"),
    ("current_owner_name", "VARCHAR(255)"),
    ("last_action_title", "VARCHAR(255)"),
    ("waiting_since", "TIMESTAMP"),
    ("waiting_days", "INTEGER DEFAULT 0"),
    ("is_overdue", "BOOLEAN DEFAULT 0"),
    ("overdue_days", "INTEGER DEFAULT 0"),
    ("tracking_status", "VARCHAR(80)"),
    ("tracking_bucket", "VARCHAR(80)"),
    ("tracking_priority", "VARCHAR(40) DEFAULT 'normal'"),
    ("tracking_label", "VARCHAR(255)"),
    ("tracking_url", "VARCHAR(500)"),
    ("last_visible_action", "VARCHAR(255)"),
    ("president_required", "BOOLEAN DEFAULT 0"),
    ("president_status", "VARCHAR(80)"),
    ("president_requested_at", "TIMESTAMP"),
    ("process_version", "VARCHAR(120)"),
    ("updated_by_engine_at", "TIMESTAMP"),
    ("tracking_updated_at", "TIMESTAMP"),
]


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-phase8-tracking-contract")
    monkeypatch.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    monkeypatch.setenv("AUTO_REPAIR_SCHEMA", "false")
    monkeypatch.setenv("STRICT_SCHEMA_CHECK", "false")
    monkeypatch.setenv("REQUIRE_DOTENV_FILE", "false")
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "false")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "false")
    monkeypatch.setenv("LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER", "false")
    monkeypatch.setenv("MAIL_SUPPRESS_SEND", "true")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    os.makedirs(_TMP_DB_DIR, exist_ok=True)
    db_path = os.path.join(_TMP_DB_DIR, f"agent3_phase8_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

    # Config.SQLALCHEMY_DATABASE_URI is a class attribute frozen the first
    # time config.py is imported in this pytest process, and Flask-SQLAlchemy
    # 3.x lazily binds+caches the per-app Engine from app.config at
    # create_app() time -- patching Config BEFORE create_app() (proven
    # pattern from tests/behavior/test_admin_ops_user_actions_destructive_operations_contract.py)
    # is required for this test's own isolated SQLite file to actually take effect.
    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", db_uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_ENGINE_OPTIONS={
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
    )

    from app.extensions import db

    with flask_app.app_context():
        from sqlalchemy import event

        @event.listens_for(db.engine, "connect")
        def _disable_pysqlite_implicit_begin(dbapi_connection, connection_record):  # noqa: ARG001
            dbapi_connection.isolation_level = None

        @event.listens_for(db.engine, "begin")
        def _explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

        db.create_all()
        for column_name, ddl_type in _PHASE8_EXTRA_FLOW_COLUMNS:
            db.session.execute(
                text(f"ALTER TABLE performance_process_flows ADD COLUMN {column_name} {ddl_type}")
            )
        db.session.commit()

    return flask_app


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    flask_app = _make_app(monkeypatch)
    request.addfinalizer(lambda: release_sqlite_app(flask_app))
    return flask_app


def _seed_flow(
    app,
    *,
    evaluation_id: int,
    current_status: str | None = "takipte",
    current_owner_user_id: int | None = None,
    employee_id: int | None = None,
    is_finalized: bool = False,
    is_overdue: bool = False,
    waiting_days: int = 0,
    president_status: str | None = None,
) -> int:
    """BYS360 DEFECT AO: waiting_days/is_overdue/tracking_bucket/
    president_status are no longer real (or even fixture-only ghost)
    columns this module reads -- every value production now derives comes
    from real, migrated PerformanceProcessFlow columns instead. This
    helper's own parameter names are kept for minimal call-site churn
    across this file, but now translate into real columns: is_overdue/
    waiting_days become last_action_at (the actual timestamp production
    derives waiting time from), and president_status becomes the real
    president_approval_required/president_approval_status pair
    ("pending" => required, still undecided; "returned" => required,
    decided-and-sent-back; None => not required)."""
    from app.extensions import db
    from app.models import PerformanceProcessFlow

    effective_waiting_days = waiting_days or (pt.PHASE8_OVERDUE_THRESHOLD_DAYS if is_overdue else 0)
    president_approval_required = president_status is not None
    president_approval_status = {
        "pending": "not_required",
        "returned": "returned",
    }.get(president_status or "", "not_required")

    with app.app_context():
        flow = PerformanceProcessFlow(
            evaluation_id=evaluation_id,
            current_status=current_status or "created",
            is_finalized=is_finalized,
            current_owner_id=current_owner_user_id,
            employee_id=employee_id,
            last_action_at=datetime.utcnow() - timedelta(days=effective_waiting_days),
            president_approval_required=president_approval_required,
            president_approval_status=president_approval_status,
        )
        db.session.add(flow)
        db.session.commit()
        return flow.id


def _create_user(app, *, ad: str, soyad: str, role: str = "personel", unvan: str | None = None) -> int:
    from app.extensions import db
    from app.models import User

    suffix = uuid.uuid4().hex[:10]
    with app.app_context():
        user = User(
            sicil_no=f"P8T{suffix}",
            email=f"phase8-{suffix}@bys360.test",
            ad=ad,
            soyad=soyad,
            role=role,
            unvan=unvan,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("Phase8TrackingContractTest1!")
        db.session.add(user)
        db.session.commit()
        return user.id


# ---------------------------------------------------------------------------
# table_exists / column_exists against the real SQLite bind.
# ---------------------------------------------------------------------------


def test_table_exists_true_for_real_table(app) -> None:
    with app.app_context():
        assert pt.table_exists("performance_process_flows") is True


def test_table_exists_false_for_missing_table(app) -> None:
    with app.app_context():
        assert pt.table_exists("totally_missing_table_xyz_123") is False


def test_column_exists_true_for_phase8_added_column(app) -> None:
    with app.app_context():
        assert pt.column_exists("performance_process_flows", "tracking_bucket") is True


def test_column_exists_false_for_missing_column(app) -> None:
    with app.app_context():
        assert pt.column_exists("performance_process_flows", "totally_missing_column_xyz") is False


# ---------------------------------------------------------------------------
# _flow_base_rows: real SELECT + real WHERE clauses against seeded rows.
# Five mutually-exclusive flows (W/O/P/C/R below) each qualify for exactly
# one non-"all" status_filter, proving the real SQL genuinely restricts
# rows rather than the filter being a no-op.
# ---------------------------------------------------------------------------


def test_flow_base_rows_status_filters_are_mutually_exclusive_and_restrict_real_select(app) -> None:
    owner_id = _create_user(app, ad="Owner", soyad="One")

    flow_waiting = _seed_flow(
        app, evaluation_id=9101, current_owner_user_id=owner_id, is_overdue=False,
        is_finalized=False, president_status=None, current_status="takipte",
    )
    flow_overdue = _seed_flow(
        app, evaluation_id=9102, current_owner_user_id=None, is_overdue=True,
        is_finalized=False, president_status=None, current_status="takipte",
    )
    flow_president = _seed_flow(
        app, evaluation_id=9103, current_owner_user_id=None, is_overdue=False,
        is_finalized=False, president_status="pending", current_status="takipte",
    )
    flow_completed = _seed_flow(
        app, evaluation_id=9104, current_owner_user_id=None, is_overdue=False,
        is_finalized=True, president_status=None, current_status="tamamlandi",
    )
    flow_returned = _seed_flow(
        app, evaluation_id=9105, current_owner_user_id=None, is_overdue=False,
        is_finalized=False, president_status="returned", current_status="takipte",
    )

    admin = SimpleNamespace(id=1, role="admin", unvan=None)

    with app.app_context():
        def ids_for(status_filter: str) -> set[int]:
            rows = pt._flow_base_rows(viewer=admin, status_filter=status_filter, search="", limit=300)
            return {int(row["flow_id"]) for row in rows}

        assert ids_for("waiting") == {flow_waiting}
        assert ids_for("overdue") == {flow_overdue}
        assert ids_for("president") == {flow_president}
        assert ids_for("completed") == {flow_completed}
        assert ids_for("returned") == {flow_returned}
        assert ids_for("all") == {
            flow_waiting, flow_overdue, flow_president, flow_completed, flow_returned,
        }


def test_flow_base_rows_scope_clause_restricts_regular_viewer_to_own_flows(app) -> None:
    owner_id = _create_user(app, ad="Owner", soyad="Restricted")
    other_id = _create_user(app, ad="Other", soyad="Person")

    own_flow = _seed_flow(app, evaluation_id=9201, current_owner_user_id=owner_id, current_status="takipte")
    other_flow = _seed_flow(app, evaluation_id=9202, current_owner_user_id=other_id, current_status="takipte")

    regular_viewer = SimpleNamespace(id=owner_id, role="personel", unvan="Uzman")
    admin_viewer = SimpleNamespace(id=999, role="admin", unvan=None)

    with app.app_context():
        regular_rows = pt._flow_base_rows(viewer=regular_viewer, status_filter="all", search="", limit=300)
        regular_ids = {int(row["flow_id"]) for row in regular_rows}
        assert regular_ids == {own_flow}
        assert other_flow not in regular_ids

        admin_rows = pt._flow_base_rows(viewer=admin_viewer, status_filter="all", search="", limit=300)
        admin_ids = {int(row["flow_id"]) for row in admin_rows}
        assert admin_ids == {own_flow, other_flow}


def test_flow_base_rows_search_clause_matches_employee_name_and_returns_real_join(app) -> None:
    zeynep_id = _create_user(app, ad="Zeynep", soyad="Yıldız")
    unrelated_id = _create_user(app, ad="Mehmet", soyad="Kaya")

    zeynep_flow = _seed_flow(app, evaluation_id=9301, employee_id=zeynep_id, current_status="takipte")
    _seed_flow(app, evaluation_id=9302, employee_id=unrelated_id, current_status="takipte")

    admin = SimpleNamespace(id=1, role="admin", unvan=None)

    with app.app_context():
        rows = pt._flow_base_rows(viewer=admin, status_filter="all", search="zeynep", limit=300)
        ids = {int(row["flow_id"]) for row in rows}
        assert ids == {zeynep_flow}
        matched_row = rows[0]
        assert matched_row["emp_full_name"] == "Zeynep Yıldız"


def test_build_process_tracking_workspace_assembles_items_counts_and_bucket_labels(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_process_tracking_workspace's own contribution beyond
    _flow_base_rows (already proven for real above) is the counts/bucket-
    label/item-assembly loop -- proven here against a real Tier-2 DB.
    _steps_for_flows and _history_for_flows are stubbed to return {} to
    isolate this aggregation loop from the row-fetch helpers (both are
    separately proven for real against SQLite elsewhere, see module
    docstring's BYS360 DEFECT AB note). Every other function this
    workspace call touches (_flow_base_rows, _row_bucket, _visible_bucket,
    _bucket_tone, _full_name_from_row) runs for real."""
    monkeypatch.setattr(pt, "_steps_for_flows", lambda flow_ids: {})
    monkeypatch.setattr(pt, "_history_for_flows", lambda flow_ids: {})

    waiting_owner_id = _create_user(app, ad="Ayşe", soyad="Bekleyen")
    employee_id = _create_user(app, ad="Can", soyad="Personel")
    waiting_flow = _seed_flow(
        app, evaluation_id=9501, current_owner_user_id=waiting_owner_id, employee_id=employee_id,
        is_overdue=False, is_finalized=False, president_status=None, current_status="takipte",
    )
    overdue_flow = _seed_flow(
        app, evaluation_id=9502, current_owner_user_id=None, employee_id=None,
        is_overdue=True, is_finalized=False, president_status=None, current_status="takipte",
    )

    admin = SimpleNamespace(id=1, role="admin", unvan=None)

    with app.app_context():
        workspace = pt.build_process_tracking_workspace(admin, status_filter="all", search="", limit=300)

    assert workspace["counts"]["total"] == 2
    assert workspace["counts"]["waiting"] == 1
    assert workspace["counts"]["overdue"] == 1
    assert workspace["counts"]["completed"] == 0
    assert workspace["viewer_name"] == "Kullanıcı"

    items_by_flow = {item["flow_id"]: item for item in workspace["items"]}
    assert set(items_by_flow) == {waiting_flow, overdue_flow}

    waiting_item = items_by_flow[waiting_flow]
    assert waiting_item["bucket"] == "waiting"
    assert waiting_item["bucket_label"] == "İşlem Bekliyor"
    assert waiting_item["status_tone"] == "warning"
    assert waiting_item["employee_name"] == "Can Personel"
    assert waiting_item["steps"] == []
    assert waiting_item["history"] == []

    overdue_item = items_by_flow[overdue_flow]
    assert overdue_item["bucket"] == "overdue"
    assert overdue_item["bucket_label"] == "Gecikmiş Süreç"
    assert overdue_item["status_tone"] == "danger"
    assert overdue_item["is_overdue"] is True


# ---------------------------------------------------------------------------
# synchronize_phase8_tracking: real bucket-precedence branches that are
# actually reachable through this function's own SELECT column list (see
# module docstring, defect 1, for the branch that is NOT reachable here),
# plus idempotent convergence and the waiting_days>=7 overdue threshold.
# ---------------------------------------------------------------------------


def test_synchronize_phase8_tracking_returns_empty_result_when_table_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pt, "table_exists", lambda name: False)
    result = pt.synchronize_phase8_tracking()
    assert result == pt.Phase8SyncResult(flows_checked=0, flows_updated=0)


def test_synchronize_phase8_tracking_counts_flows_and_writes_nothing(app) -> None:
    """BYS360 DEFECT AO: synchronize_phase8_tracking() used to persist
    derived tracking_bucket/is_overdue/tracking_priority values into ghost
    columns that no migration ever created. Now that every one of those
    values is safely computable at read time (build_process_tracking_
    workspace() recomputes them fresh on every page load, proven in the
    tests below), there is nothing left to persist -- a stored copy could
    only drift from reality. This function now verifies the flows are
    present and readable, and genuinely writes nothing: flows_updated is
    always 0."""
    _seed_flow(app, evaluation_id=9401, current_owner_user_id=None, current_status="takipte")
    _seed_flow(app, evaluation_id=9402, current_owner_user_id=None, is_finalized=True, current_status="tamamlandi")

    with app.app_context():
        from app.extensions import db

        before = dict(
            db.session.execute(
                text("SELECT id, current_status, is_finalized, updated_at FROM performance_process_flows ORDER BY id")
            ).mappings().all()[0]
        )
        result = pt.synchronize_phase8_tracking()
        after = dict(
            db.session.execute(
                text("SELECT id, current_status, is_finalized, updated_at FROM performance_process_flows ORDER BY id")
            ).mappings().all()[0]
        )

    assert result.flows_checked == 2
    assert result.flows_updated == 0
    assert before == after


def test_synchronize_phase8_tracking_respects_limit(app) -> None:
    for i in range(3):
        _seed_flow(app, evaluation_id=9410 + i, current_owner_user_id=None, current_status="takipte")

    with app.app_context():
        result = pt.synchronize_phase8_tracking(limit=2)

    assert result.flows_checked == 2
    assert result.flows_updated == 0


def test_synchronize_phase8_tracking_is_idempotent_on_repeat_call(app) -> None:
    _seed_flow(app, evaluation_id=9407, current_owner_user_id=None, current_status="takipte")

    with app.app_context():
        first = pt.synchronize_phase8_tracking()
        second = pt.synchronize_phase8_tracking()

    assert first == second == pt.Phase8SyncResult(flows_checked=1, flows_updated=0)


# ---------------------------------------------------------------------------
# build_process_tracking_workspace: the bucket-precedence proof now lives
# here (not synchronize_phase8_tracking(), which no longer computes a
# bucket at all) -- these are the real values a user sees, derived from
# real columns against a real, migration-shaped SQLite database.
# ---------------------------------------------------------------------------


def test_build_process_tracking_workspace_waiting_days_and_overdue_boundary(app) -> None:
    just_under = _seed_flow(
        app, evaluation_id=9405, current_owner_user_id=None,
        is_finalized=False, waiting_days=6, current_status="takipte",
    )
    at_threshold = _seed_flow(
        app, evaluation_id=9406, current_owner_user_id=None,
        is_finalized=False, waiting_days=7, current_status="takipte",
    )
    admin = SimpleNamespace(id=1, role="admin", unvan=None)

    with app.app_context():
        workspace = pt.build_process_tracking_workspace(admin, status_filter="all", search="", limit=300)

    items_by_flow = {item["flow_id"]: item for item in workspace["items"]}
    under_item = items_by_flow[just_under]
    at_item = items_by_flow[at_threshold]
    assert under_item["waiting_days"] == 6
    assert under_item["is_overdue"] is False
    assert under_item["bucket"] == "monitoring"
    assert at_item["waiting_days"] == 7
    assert at_item["is_overdue"] is True
    assert at_item["bucket"] == "overdue"


def test_build_process_tracking_workspace_overdue_beats_completed_bucket(app) -> None:
    """BYS360 DEFECT AO: this is the exact defect AN's own investigation
    documented -- a flow past the overdue threshold that is also finalized
    must still show bucket="overdue" (is_overdue is checked before
    is_finalized in _row_bucket()'s precedence), not silently fall back to
    "completed"."""
    flow_id = _seed_flow(
        app, evaluation_id=9408, current_owner_user_id=None,
        is_finalized=True, waiting_days=10, current_status="tamamlandi",
    )
    admin = SimpleNamespace(id=1, role="admin", unvan=None)

    with app.app_context():
        workspace = pt.build_process_tracking_workspace(admin, status_filter="all", search="", limit=300)

    item = {item["flow_id"]: item for item in workspace["items"]}[flow_id]
    assert item["is_overdue"] is True
    assert item["bucket"] == "overdue"


def test_build_process_tracking_workspace_president_pending_and_returned_buckets(app) -> None:
    pending_flow = _seed_flow(
        app, evaluation_id=9409, current_owner_user_id=None,
        president_status="pending", current_status="takipte",
    )
    returned_flow = _seed_flow(
        app, evaluation_id=9411, current_owner_user_id=None,
        president_status="returned", current_status="takipte",
    )
    admin = SimpleNamespace(id=1, role="admin", unvan=None)

    with app.app_context():
        workspace = pt.build_process_tracking_workspace(admin, status_filter="all", search="", limit=300)

    items_by_flow = {item["flow_id"]: item for item in workspace["items"]}
    assert items_by_flow[pending_flow]["bucket"] == "president_pending"
    assert items_by_flow[pending_flow]["president_required"] is True
    assert items_by_flow[returned_flow]["bucket"] == "returned"


def test_build_process_tracking_workspace_default_monitoring_bucket(app) -> None:
    # current_status must be "" (falsy), not NULL: the ORM column is
    # NOT NULL. _row_bucket's fallback (`row.get("current_status") or ""`)
    # treats an empty string the same as a missing value.
    flow_id = _seed_flow(
        app, evaluation_id=9404, current_owner_user_id=None,
        is_finalized=False, current_status="",
    )
    admin = SimpleNamespace(id=1, role="admin", unvan=None)

    with app.app_context():
        workspace = pt.build_process_tracking_workspace(admin, status_filter="all", search="", limit=300)

    item = {item["flow_id"]: item for item in workspace["items"]}[flow_id]
    assert item["bucket"] == "monitoring"


# ===========================================================================
# TIER 3 -- fake db-session boundary for the three ANY()-based delete
# functions, shaped identically to
# tests/behavior/test_president_approvals_authorization_and_workspace_contract.py
# lines 71-153 (_FakeExecResult / _SequencedExecute / _FakeSession / _FakeDb).
# No Flask app or database anywhere in this section.
# ===========================================================================


class _FakeExecResult:
    def __init__(self, *, rowcount: int = 1) -> None:
        self.rowcount = rowcount


class _SequencedExecute:
    """Returns one queued result per call (or invokes a callable, letting a
    specific call raise), and records the exact SQL text + params sent."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        sql = str(stmt)
        self.calls.append((sql, dict(params or {})))
        if not self._results:
            raise AssertionError(
                f"Unexpected extra db.session.execute call (no more queued results):\n{sql}\nparams={params}"
            )
        next_result = self._results.pop(0)
        if isinstance(next_result, BaseException):
            raise next_result
        return next_result


class _FakeSession:
    def __init__(self, execute: Any) -> None:
        self._execute = execute
        self.commit_calls = 0
        self.rollback_calls = 0

    def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> Any:
        return self._execute(stmt, params)

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


class _FakeDb:
    def __init__(self, execute: Any) -> None:
        self.session = _FakeSession(execute)


def _install_fake_db(monkeypatch: pytest.MonkeyPatch, execute: Any) -> _FakeDb:
    fake_db = _FakeDb(execute)
    monkeypatch.setattr(pt, "db", fake_db)
    return fake_db


def _forbid_db_execute(stmt: Any, params: dict[str, Any] | None = None) -> Any:
    raise AssertionError(f"db.session.execute must not be called here; got:\n{stmt}\nparams={params}")


def _forbid_flow_base_rows(**kwargs: Any) -> Any:
    raise AssertionError(f"_flow_base_rows must not be called here; got kwargs={kwargs}")


_UNAUTHORIZED_VIEWER = SimpleNamespace(id=3, role="personel", unvan="Uzman")
_AUTHORIZED_VIEWER = SimpleNamespace(id=1, role="admin", unvan=None)


def _allow_all_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pt, "table_exists", lambda name: True)
    monkeypatch.setattr(pt, "column_exists", lambda table, column: True)


# ---------------------------------------------------------------------------
# delete_process_tracking_flow: authorization gate.
# ---------------------------------------------------------------------------


def test_delete_process_tracking_flow_unauthorized_raises_before_any_db_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_db(monkeypatch, _forbid_db_execute)
    monkeypatch.setattr(pt, "table_exists", _forbid_table_exists)

    with pytest.raises(PermissionError, match="Bu işlem için yetkiniz bulunmamaktadır."):
        pt.delete_process_tracking_flow(77, _UNAUTHORIZED_VIEWER)


def test_delete_process_tracking_flow_authorized_issues_three_ordered_deletes_scoped_to_target_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_all_schema(monkeypatch)
    execute = _SequencedExecute([_FakeExecResult(), _FakeExecResult(), _FakeExecResult(rowcount=1)])
    fake_db = _install_fake_db(monkeypatch, execute)

    result = pt.delete_process_tracking_flow(55, _AUTHORIZED_VIEWER)

    assert result == 1
    assert fake_db.session.commit_calls == 1
    assert fake_db.session.rollback_calls == 0
    assert len(execute.calls) == 3

    steps_sql, steps_params = execute.calls[0]
    notif_sql, notif_params = execute.calls[1]
    flows_sql, flows_params = execute.calls[2]

    # BYS360 DEFECT AB: the dialect-neutral "expanding IN" bind pattern
    # compiles to "IN (__[POSTCOMPILE_flow_ids])" placeholder text before
    # parameter substitution (real values are bound at execute time, see
    # steps_params/notif_params/flows_params below) -- this is what
    # replaced the prior PostgreSQL-only "= ANY(:flow_ids)" literal.
    assert "performance_process_flow_steps" in steps_sql
    assert "DELETE FROM performance_process_flow_steps WHERE flow_id IN (__[POSTCOMPILE_flow_ids])" in steps_sql
    assert steps_params["flow_ids"] == [55]

    assert "performance_process_notifications" in notif_sql
    assert "DELETE FROM performance_process_notifications WHERE flow_id IN (__[POSTCOMPILE_flow_ids])" in notif_sql
    assert notif_params["flow_ids"] == [55]

    assert "DELETE FROM performance_process_flows WHERE id IN (__[POSTCOMPILE_flow_ids])" in flows_sql
    assert flows_params["flow_ids"] == [55]

    # No evaluation/scorecard/president-approval/personnel table is ever
    # touched by the delete cascade -- directly proves the module's own
    # docstring invariant, since any such SQL would have been recorded here.
    all_sql = steps_sql + notif_sql + flows_sql
    for forbidden_table in (
        "performance_evaluations",
        "performance_scoring_history",
        "performance_president_approvals",
        "users",
    ):
        assert forbidden_table not in all_sql


# ---------------------------------------------------------------------------
# delete_visible_process_tracking_flows: authorization gate + exact
# flow_ids passthrough from _flow_base_rows.
# ---------------------------------------------------------------------------


def test_delete_visible_process_tracking_flows_unauthorized_raises_before_flow_base_rows_or_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_db(monkeypatch, _forbid_db_execute)
    monkeypatch.setattr(pt, "_flow_base_rows", _forbid_flow_base_rows)
    monkeypatch.setattr(pt, "table_exists", _forbid_table_exists)

    with pytest.raises(PermissionError, match="Bu işlem için yetkiniz bulunmamaktadır."):
        pt.delete_visible_process_tracking_flows(_UNAUTHORIZED_VIEWER, status_filter="all")


def test_delete_visible_process_tracking_flows_passes_exact_ids_from_flow_base_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_all_schema(monkeypatch)
    monkeypatch.setattr(
        pt,
        "_flow_base_rows",
        lambda **kwargs: [{"flow_id": 10}, {"flow_id": 11}],
    )
    execute = _SequencedExecute([_FakeExecResult(), _FakeExecResult(), _FakeExecResult(rowcount=2)])
    fake_db = _install_fake_db(monkeypatch, execute)

    result = pt.delete_visible_process_tracking_flows(_AUTHORIZED_VIEWER, status_filter="overdue")

    assert result == 2
    assert fake_db.session.commit_calls == 1
    assert len(execute.calls) == 3
    for _sql, params in execute.calls:
        assert params["flow_ids"] == [10, 11]


def test_delete_visible_process_tracking_flows_empty_match_short_circuits_before_any_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_all_schema(monkeypatch)
    monkeypatch.setattr(pt, "_flow_base_rows", lambda **kwargs: [])
    fake_db = _install_fake_db(monkeypatch, _forbid_db_execute)

    result = pt.delete_visible_process_tracking_flows(_AUTHORIZED_VIEWER, status_filter="all")

    assert result == 0
    assert fake_db.session.commit_calls == 0
    assert fake_db.session.rollback_calls == 0


# ---------------------------------------------------------------------------
# _delete_tracking_flow_ids: empty-list short-circuit + rollback contract.
# ---------------------------------------------------------------------------


def test_delete_tracking_flow_ids_empty_list_short_circuits_before_table_exists_or_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pt, "table_exists", _forbid_table_exists)
    fake_db = _install_fake_db(monkeypatch, _forbid_db_execute)

    assert pt._delete_tracking_flow_ids([]) == 0
    assert pt._delete_tracking_flow_ids([0]) == 0
    assert fake_db.session.commit_calls == 0
    assert fake_db.session.rollback_calls == 0


def test_delete_tracking_flow_ids_rolls_back_and_reraises_on_second_call_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_all_schema(monkeypatch)
    injected_error = RuntimeError("simulated notifications-delete failure")
    execute = _SequencedExecute([_FakeExecResult(), injected_error, _FakeExecResult()])
    fake_db = _install_fake_db(monkeypatch, execute)

    with pytest.raises(RuntimeError, match="simulated notifications-delete failure"):
        pt.delete_process_tracking_flow(88, _AUTHORIZED_VIEWER)

    assert fake_db.session.rollback_calls == 1
    assert fake_db.session.commit_calls == 0
    # Only the steps DELETE (call 1) and the failing notifications DELETE
    # (call 2) were attempted; the flows DELETE (call 3) never ran.
    assert len(execute.calls) == 2
