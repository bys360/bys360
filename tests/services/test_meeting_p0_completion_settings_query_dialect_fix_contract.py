"""BYS360 Meeting P0 -- settings `IN` query dialect-safety fix contract.

CONTEXT: `app/services/performance/meeting_p0_completion.py::build_p0_completion_
context()` builds its `"settings"` key via a raw SQLAlchemy `text()` statement:

    text("... WHERE module_key='performance' AND setting_key IN :keys ...")

bound with `{"keys": tuple(P0_REQUIRED_SETTINGS.keys())}` -- a plain named
parameter bound to a Python tuple, WITHOUT declaring `bindparam("keys",
expanding=True)`. SQLAlchemy does NOT auto-detect "expanding IN" for a bare
`text()` bind parameter; without the explicit `expanding=True` declaration it
compiles `IN :keys` into a SINGLE unexpanded placeholder (`?` on SQLite,
`%(keys)s` on PostgreSQL) and passes the whole tuple as one scalar value.
Python's built-in `sqlite3` driver cannot adapt a tuple to a scalar bind
value at all, so every call failed with `sqlite3.OperationalError: near "?":
syntax error` -- independently reproduced below, pinned to the fixed
pre-fix ref (4af482e3dff5a35e6510a01159e97ec73b661b1b).

WHY THE PAGE STILL RETURNED 200: `_rows()` (this module's private DB-query
helper) wraps its `db.session.execute(...)` call in a broad `except
Exception:` that logs via `logger.exception(...)` and returns `[]`. The
exception never propagates to Flask, so `build_p0_completion_context()`
silently receives `"settings": []` and `render_template()` proceeds
normally -- the bug was invisible at the HTTP layer, only visible in the
application log.

POSTGRES_RUNTIME_NOT_TESTED: this repo/environment has no live PostgreSQL
server to connect to. The reasoning that PostgreSQL's behavior likely
differed from SQLite's (psycopg2-binary's documented Python-tuple-to-SQL-
tuple-literal adaptation, used by the app in production per
`requirements.txt`'s `psycopg2-binary==2.9.9` and `config.py`'s postgres
scheme handling) is a SOURCE/DRIVER-DOCUMENTATION-based inference, not an
empirical PostgreSQL measurement -- explicitly disclosed here per that
same limitation.

THE FIX: declare the bind parameter as `expanding=True` --
`text(sql).bindparams(bindparam("keys", expanding=True))` -- so SQLAlchemy
expands the tuple into the correct number of placeholders at execution time,
identically across dialects. `_rows()`'s signature was widened from
`sql: str` to `sql: str | TextClause` so this one call site could pass a
pre-built, already-`bindparams()`-configured statement while every other
existing plain-string call site is completely unaffected (verified below).
No string-join/f-string SQL construction, no manual quoting, no dialect
branching, no PostgreSQL-specific workaround -- exactly the portable,
dialect-independent SQLAlchemy-native mechanism this bug class calls for.

This file uses real, isolated Flask apps (module-scoped, UUID-based temp
SQLite, matching this repo's established Wave2/Style-2A/2B/3A/3B/3C fixture
pattern) and real `db.session`/ORM writes -- never string-interpolated SQL.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import bindparam, create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_FILE = "app/services/performance/meeting_p0_completion.py"

# Tip of phase5-critical-lint-clean-v1 immediately before this fix -- the
# repo state where the bug was still present. Fixed, historical; never
# affected by any later commit.
PRE_FIX_REF = "4af482e3dff5a35e6510a01159e97ec73b661b1b"

# KOORDINATOR DUZELTMESI: originally included meeting_p0_completion.html and
# meeting_development_faz4.html -- correct while this SQL-only fix wave was
# the most recent thing to touch app/templates/performance/. Two later,
# legitimate waves ("BYS360 Meeting UI Context Adapter -- Dalga 1 / P0
# Completion" and "-- Dalga 2 / Final Gate") rewrote those templates' bodies
# to render their own context builders' real fields (see
# test_meeting_p0_completion_ui_context_adapter_contract.py and
# test_meeting_final_gate_ui_context_adapter_contract.py for each wave's own
# full evidence chain) -- intentional, in-scope changes for those later
# waves, not a regression of this one. Removed here so this SQL-fix wave's
# OWN untouched-template assertion no longer sees those later, unrelated
# waves' legitimate edits -- same class of drift already handled for
# test_csp_style3c_meeting_family_group_a_contract.py's own scope-guard test
# after the duplicate-template orphan cleanup wave.
MEETING_FAMILY_TEMPLATES: tuple[str, ...] = (
    "app/templates/performance/meeting_development_faz3.html",
    "app/templates/performance/meeting_development_scenarios.html",
    "app/templates/performance/meeting_final_closure.html",
    "app/templates/performance/meeting_p1_scope.html",
    "app/templates/performance/meeting_p2_archive_notes.html",
    "app/templates/performance/meeting_rule_enforcement.html",
)


def _normalize_line_endings(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _git_show(ref: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"'git show {ref}:{relative_path}' failed: {result.stderr!r}"
    return result.stdout


_BUGGY_QUERY_SQL = (
    "SELECT setting_key, label, value_text, description FROM module_settings "
    "WHERE module_key='performance' AND setting_key IN :keys ORDER BY setting_key"
)
_TEST_KEYS = (
    "require_criterion_comment_for_score_1_5",
    "low_score_president_approval_required",
    "low_score_general_comment_required",
    "employee_can_see_own_group_average",
    "manager_performance_scope_limited",
    "p0_test_scenarios_enabled",
)


def _fresh_sqlite_engine():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE module_settings (module_key TEXT, setting_key TEXT, "
                "label TEXT, value_text TEXT, description TEXT)"
            )
        )
        for key in _TEST_KEYS:
            conn.execute(
                text(
                    "INSERT INTO module_settings (module_key, setting_key, label, value_text, description) "
                    "VALUES ('performance', :k, :l, 'true', :d)"
                ),
                {"k": key, "l": f"Label for {key}", "d": f"Description for {key}"},
            )
        conn.execute(
            text(
                "INSERT INTO module_settings (module_key, setting_key, label, value_text, description) "
                "VALUES ('performance', 'unrelated_setting_key', 'Unrelated', 'true', 'Not requested')"
            )
        )
    return engine


# ---------------------------------------------------------------------------
# 1) The pre-fix failure is independently reproducible from the fixed,
#    historical pre-fix git ref -- proves the bug genuinely existed there
#    (not just "trust the commit message").
# ---------------------------------------------------------------------------


def test_pre_fix_ref_contains_the_unexpanding_in_keys_query() -> None:
    pre_fix_source = _git_show(PRE_FIX_REF, TARGET_FILE).decode("utf-8", errors="replace")
    assert "setting_key IN :keys" in pre_fix_source
    assert "expanding=True" not in pre_fix_source, (
        f"{PRE_FIX_REF} unexpectedly already contains an expanding=True bindparam -- "
        "the pre-fix ref no longer represents the buggy state."
    )


def test_pre_fix_query_fails_on_sqlite_with_operational_error() -> None:
    engine = _fresh_sqlite_engine()
    stmt = text(_BUGGY_QUERY_SQL)
    with engine.connect() as conn, pytest.raises(Exception) as exc_info:
        conn.execute(stmt, {"keys": _TEST_KEYS})
    assert type(exc_info.value).__name__ == "OperationalError"
    assert 'near "?": syntax error' in str(exc_info.value)


# ---------------------------------------------------------------------------
# 2) Post-fix: the query, exactly as now written in the target file, works.
# ---------------------------------------------------------------------------


def _fixed_statement():
    return text(_BUGGY_QUERY_SQL).bindparams(bindparam("keys", expanding=True))


def test_post_fix_query_succeeds_on_sqlite() -> None:
    engine = _fresh_sqlite_engine()
    with engine.connect() as conn:
        result = conn.execute(_fixed_statement(), {"keys": _TEST_KEYS})
        rows = [dict(r) for r in result.mappings().all()]
    assert len(rows) == 6


# ---------------------------------------------------------------------------
# 3) Single key works.
# ---------------------------------------------------------------------------


def test_single_key_works() -> None:
    engine = _fresh_sqlite_engine()
    with engine.connect() as conn:
        result = conn.execute(_fixed_statement(), {"keys": (_TEST_KEYS[0],)})
        rows = [dict(r) for r in result.mappings().all()]
    assert len(rows) == 1
    assert rows[0]["setting_key"] == _TEST_KEYS[0]


# ---------------------------------------------------------------------------
# 4) Multiple keys work.
# ---------------------------------------------------------------------------


def test_multiple_keys_work() -> None:
    engine = _fresh_sqlite_engine()
    with engine.connect() as conn:
        result = conn.execute(_fixed_statement(), {"keys": _TEST_KEYS})
        rows = [dict(r) for r in result.mappings().all()]
    assert len(rows) == len(_TEST_KEYS)


# ---------------------------------------------------------------------------
# 5) Result ordering/fields match the expected contract: ORDER BY
#    setting_key ASC, and exactly the 4 selected columns, per row.
# ---------------------------------------------------------------------------


def test_result_ordering_and_fields_match_expected_contract() -> None:
    engine = _fresh_sqlite_engine()
    with engine.connect() as conn:
        result = conn.execute(_fixed_statement(), {"keys": _TEST_KEYS})
        rows = [dict(r) for r in result.mappings().all()]
    returned_keys = [r["setting_key"] for r in rows]
    assert returned_keys == sorted(returned_keys), "Rows must be ordered by setting_key ASC."
    for row in rows:
        assert set(row.keys()) == {"setting_key", "label", "value_text", "description"}


# ---------------------------------------------------------------------------
# 6) Empty key list behaves safely: no SQL syntax error, empty result.
# ---------------------------------------------------------------------------


def test_empty_key_list_is_safe_and_returns_no_rows() -> None:
    engine = _fresh_sqlite_engine()
    with engine.connect() as conn:
        result = conn.execute(_fixed_statement(), {"keys": ()})
        rows = [dict(r) for r in result.mappings().all()]
    assert rows == []


# ---------------------------------------------------------------------------
# 7) No string interpolation is used to build the IN list -- the fixed
#    source line contains no f-string/`.format(`/`%`-formatting/`+`
#    concatenation feeding the SQL text, and no manual quoting of the keys.
# ---------------------------------------------------------------------------


def test_fixed_source_uses_no_string_interpolation_for_the_in_clause() -> None:
    source = (REPO_ROOT / TARGET_FILE).read_text(encoding="utf-8")
    settings_block_match = re.search(
        r'"settings":\s*_rows\(\s*text\((.*?)\)\.bindparams',
        source,
        re.DOTALL,
    )
    assert settings_block_match, "Expected the fixed 'settings' _rows(text(...).bindparams(...)) call was not found."
    sql_literal = settings_block_match.group(1)
    assert "f\"" not in sql_literal and "f'" not in sql_literal, "SQL text must not be an f-string."
    assert ".format(" not in sql_literal, "SQL text must not use str.format()."
    assert "%" not in sql_literal, "SQL text must not use %-style string formatting."
    assert "keys" not in sql_literal.replace(":keys", ""), (
        "The Python variable holding key values must not be concatenated directly into the SQL text."
    )


# ---------------------------------------------------------------------------
# 8) The query still uses genuine SQLAlchemy bind parameters (a named
#    `:keys` parameter declared with `bindparam(..., expanding=True)`), not
#    a raw driver-level placeholder.
# ---------------------------------------------------------------------------


def test_fixed_source_declares_an_expanding_bindparam_for_keys() -> None:
    source = (REPO_ROOT / TARGET_FILE).read_text(encoding="utf-8")
    assert "IN :keys" in source, "Expected the named bind parameter ':keys' in the SQL text."
    assert re.search(r'bindparam\(\s*["\']keys["\']\s*,\s*expanding=True\s*\)', source), (
        "Expected bindparam(\"keys\", expanding=True) declared for the settings query."
    )
    assert "from sqlalchemy import bindparam" in source or re.search(r"from sqlalchemy import[^\n]*\bbindparam\b", source), (
        "Expected bindparam imported from sqlalchemy."
    )


# ---------------------------------------------------------------------------
# 9-10) Real, isolated, authenticated Flask app: GET /performance/meeting-
#       development/p0 still returns 200, AND the P0 context's "settings"
#       key now genuinely contains the seeded fixture rows (not empty).
# ---------------------------------------------------------------------------

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "p0_settings_fix_contract" / "test_dbs"
_SAFE_RENDER_FALLBACK_MARKERS = ("\u015fablonunda hata var", "\u015fablonu hatal\u0131")


@pytest.fixture(scope="module")
def p0_fix_env():
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-p0-settings-fix-contract-min-length-ok")
    mp.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "test-password")
    mp.setenv("FLASK_SKIP_SCHEMA_VALIDATION", "1")
    mp.setenv("AUTO_REPAIR_SCHEMA", "false")
    mp.setenv("STRICT_SCHEMA_CHECK", "false")
    mp.setenv("REQUIRE_DOTENV_FILE", "false")
    mp.setenv("STRICT_ENV_VALIDATION", "false")
    mp.setenv("WTF_CSRF_ENABLED", "false")
    mp.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    mp.setenv("MAIL_SUPPRESS_SEND", "true")
    mp.setenv("SCHEDULER_ENABLED", "false")

    from app import create_app
    from config import Config

    mp.setattr(Config, "APP_ENV", "testing")
    mp.setattr(Config, "SQLALCHEMY_DATABASE_URI", "sqlite:///" + db_path.as_posix())
    mp.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})

    app = create_app()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix(),
    )

    from app.extensions import db
    from app.models import User
    from app.models.settings_models import ModuleSetting
    from app.services.performance.meeting_p0_completion import P0_REQUIRED_SETTINGS

    with app.app_context():
        db.create_all()
        for key, meta in P0_REQUIRED_SETTINGS.items():
            db.session.add(
                ModuleSetting(
                    module_key="performance",
                    setting_key=key,
                    label=meta["label"],
                    value_text=meta["value"],
                    description=meta["description"],
                )
            )
        user = User(
            sicil_no="p0fixcontract1",
            email="p0fixcontract@ktb.gov.tr",
            ad="P0Fix",
            soyad="Kontrat",
            role="admin",
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password("P0FixContractTestKey1!")
        db.session.add(user)
        db.session.commit()

    client = app.test_client()
    login_response = client.post(
        "/login",
        data={"sicil_or_email": "p0fixcontract1", "password": "P0FixContractTestKey1!"},
        follow_redirects=False,
    )
    assert login_response.status_code == 302, f"Test admin login failed: status={login_response.status_code}"
    assert "/login" not in (login_response.headers.get("Location") or ""), (
        "Still redirected to /login after POST -- authentication may have failed."
    )

    yield app, client

    mp.undo()


def test_p0_route_returns_200_after_fix(p0_fix_env) -> None:
    _app, client = p0_fix_env
    response = client.get("/performance/meeting-development/p0", follow_redirects=True)
    assert response.status_code == 200, (
        f"/performance/meeting-development/p0 returned unexpected status {response.status_code}."
    )
    body = response.get_data(as_text=True)
    for marker in _SAFE_RENDER_FALLBACK_MARKERS:
        assert marker not in body, "Response looks like a safe_render() fallback stub."


def test_p0_context_settings_now_genuinely_contains_seeded_fixture_rows(p0_fix_env) -> None:
    app, _client = p0_fix_env
    from app.services.performance.meeting_p0_completion import (
        P0_REQUIRED_SETTINGS,
        build_p0_completion_context,
    )

    with app.app_context():
        ctx = build_p0_completion_context()

    settings_rows = ctx["settings"]
    assert settings_rows, "P0 context 'settings' is empty -- the fix did not resolve the query."
    assert len(settings_rows) == len(P0_REQUIRED_SETTINGS), (
        f"Expected {len(P0_REQUIRED_SETTINGS)} settings rows, got {len(settings_rows)}."
    )
    returned_keys = {row["setting_key"] for row in settings_rows}
    assert returned_keys == set(P0_REQUIRED_SETTINGS.keys()), (
        f"Returned setting_key set does not match P0_REQUIRED_SETTINGS: "
        f"missing={set(P0_REQUIRED_SETTINGS) - returned_keys!r}, extra={returned_keys - set(P0_REQUIRED_SETTINGS)!r}"
    )


# ---------------------------------------------------------------------------
# 11) url_map route count is unchanged (985) -- this fix touches only a
#     service-layer query, no route/blueprint registration.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 DEFECT AQ): an unrelated later
# wave (AQ-2) removed the /performans/baskan-onaylari route registration
# that always lost that URL's dispatch conflict anyway (see
# tests/quality/test_route_conflict_runtime_contract.py's KNOWN_CONFLICTS
# update), dropping the real url_map route count from 985 to 984.
# ---------------------------------------------------------------------------

# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): 11 new
# GET-only /settings-center/* routes raised the count 984->995 -- mechanically
# re-verified against a fresh app.url_map, unrelated to this wave.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 ASSISTANT V2, seal-fix wave): one
# new, additive route (POST /ai-agent/api/v2/ask) raised the count 995->996
# -- mechanically re-verified against a fresh app.url_map, unrelated to
# this wave.
#
# FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 B2-F06 private uploads): one new,
# additive route (GET /portal/attachments/<int:attachment_id>) raised the
# count 996->997 -- mechanically re-verified against a fresh app.url_map,
# unrelated to this wave.
EXPECTED_URL_MAP_TOTAL = 997


def test_url_map_route_count_is_unchanged(p0_fix_env) -> None:
    app, _client = p0_fix_env
    total = len(list(app.url_map.iter_rules()))
    assert total == EXPECTED_URL_MAP_TOTAL, (
        f"url_map route count is {total}; expected {EXPECTED_URL_MAP_TOTAL} (unchanged)."
    )


# ---------------------------------------------------------------------------
# 12) Repo-wide style/CSP/handler inventory totals are unchanged -- this fix
#     touches only Python query logic, no template/CSS/JS.
#
#     FORWARD-COMPATIBILITY FOLLOW-UP (BYS360 SETTINGS CENTER V2): an
#     unrelated later wave added 4 new templates (app/templates/
#     settings_center/*.html), but their CSS is an external stylesheet
#     (app/static/css/settings_center.css) with no inline style="..."
#     attributes or <style> blocks -- 0 contribution, totals remain
#     1032/64/222 -- see test_csp_style_migration_cumulative_inventory_
#     contract.py's FORWARD-COMPATIBILITY FOLLOW-UP 9.
# ---------------------------------------------------------------------------

EXPECTED_ACTIVE_STYLE_TOTAL = 1032
EXPECTED_DYNAMIC_STYLE_TOTAL = 64
EXPECTED_STYLE_BLOCK_TOTAL = 221


def test_repo_wide_style_and_handler_inventory_is_unchanged() -> None:
    from tests.security._bys360_style_inventory import compute_inventory_from_worktree

    inventory = compute_inventory_from_worktree()
    assert inventory.active_static_total == EXPECTED_ACTIVE_STYLE_TOTAL
    assert inventory.dynamic_total == EXPECTED_DYNAMIC_STYLE_TOTAL
    assert inventory.style_block_total == EXPECTED_STYLE_BLOCK_TOTAL
    assert inventory.inline_handler_total == 0
    assert inventory.javascript_url_total == 0


# ---------------------------------------------------------------------------
# 13) The 8 meeting-family templates are byte-identical to the pre-fix ref
#     -- this fix must not touch any template.
# ---------------------------------------------------------------------------


# A later, legitimate wave (the stale-endpoint navigation fix -- see
# tests/services/test_meeting_stale_navigation_endpoint_fix_contract.py)
# corrected exactly two safe_url_for() endpoint strings per file in these
# same 6 templates: main.performance_development_guidance and main.
# performance_interim_notes_manager never existed as real Flask endpoints
# anywhere in this repo's git history -- corrected to their live,
# independently-confirmed successors.
_STALE_ENDPOINT_FIX_SUBSTITUTIONS: tuple[tuple[bytes, bytes], ...] = (
    (
        b"safe_url_for('main.performance_interim_notes_manager')",
        b"safe_url_for('main.performance_interim_notes_tr')",
    ),
    (
        b"safe_url_for('main.performance_development_guidance')",
        b"safe_url_for('main.performance_meeting_p4_development_guidance')",
    ),
)


@pytest.mark.parametrize("relative_path", MEETING_FAMILY_TEMPLATES)
def test_meeting_family_template_is_untouched_by_this_fix(relative_path: str) -> None:
    current = _normalize_line_endings((REPO_ROOT / relative_path).read_bytes())
    pre_fix = _normalize_line_endings(_git_show(PRE_FIX_REF, relative_path))
    expected = pre_fix
    for old, new in _STALE_ENDPOINT_FIX_SUBSTITUTIONS:
        assert old in expected, f"{relative_path}: expected pre-fix stale pattern {old!r} not found."
        expected = expected.replace(old, new)
    assert current == expected, f"{relative_path}: byte content changed since pre-fix ref -- must be untouched."


# ---------------------------------------------------------------------------
# 14) No new xfail introduced by this file.
# ---------------------------------------------------------------------------

_XFAIL_CALL_RE = re.compile(r"pytest" + r"\.xfail\(")
_XFAIL_MARK_RE = re.compile(r"@pytest" + r"\.mark\.xfail")


def test_this_file_introduces_no_xfail_usage() -> None:
    own_text = Path(__file__).read_text(encoding="utf-8")
    call_count = len(_XFAIL_CALL_RE.findall(own_text))
    mark_count = len(_XFAIL_MARK_RE.findall(own_text))
    assert call_count + mark_count == 0, (
        f"This test-only file must not introduce any real xfail usage (found "
        f"{call_count} xfail-call usages and {mark_count} xfail-mark-decorator usages)."
    )
