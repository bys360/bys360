"""BYS360 Meeting Final Gate -- canonical menu source correction contract.

CONTEXT: the navigation-wiring wave (see `test_meeting_development_p0_
navigation_contract.py`) closed 9 real `build_final_gate_context()` errors
by wiring 4 Meeting Development screens into the real navigation/visibility
system. 5 of those 9 errors were genuine `REQUIRED_TOKENS` misses against
`app/templates/base.html` -- base.html is the actual, sole presentation
layer for sidebar labels/hrefs, so a literal scan of it is a correct proxy
for "is this screen's nav link rendered". The other 4 targeted
`app/menu_registry.py`, and the wave closed them by adding 4
`FORCE_VISIBLE_MENU_ROLES.setdefault(...)` blocks to that file -- which
worked (the gate went green), but only because `REQUIRED_TOKENS` did a raw
substring scan of `menu_registry.py`'s own file text, and
`FORCE_VISIBLE_MENU_ROLES` happens to be write-only dead state: grepped
repo-wide, it is never read anywhere in the actual visibility-computation
chain (confirmed independently in this wave and the prior one). Those 4
blocks were therefore dead literals whose only real effect was satisfying
the gate's own text scan -- a form of technical debt this wave removes.

Git archaeology (see this wave's coordinator report) found `app/
menu_registry.py`'s own historical comments ("BYS360 P11-D2/P11-D3: ...
veri bloğu data modülüne taşındı") already present at the repo's earliest
squashed commit, proving that within all observable history this file has
never been the canonical home for menu-item data -- it is a bridge/
re-export module. The real canonical registration lives in `app.
menu_registry_data_sections.MENU_SECTIONS`. `REQUIRED_TOKENS["app/
menu_registry.py"]` was therefore checking the WRONG_TARGET_FILE, not a
once-correct-now-stale one (STALE_GATE_EXPECTATION would require it to
have once been true; it never was, within observable history).

THIS WAVE'S FIX (behavioral, not textual):
1. Removed `REQUIRED_TOKENS["app/menu_registry.py"]` entirely --
   `app/services/performance/meeting_development_final_gate.py` no longer
   does a raw-text scan of that file for these 4 keys.
2. Removed the 4 dead `FORCE_VISIBLE_MENU_ROLES` blocks this wave itself
   added to `menu_registry.py` (the pre-existing legacy ones for President
   Approvals / Phase 9 / Phase 10 are untouched -- separate, disclosed
   technical debt, out of this wave's scope).
3. Added `REQUIRED_CANONICAL_MENU_ITEMS` + `_menu_item_canonically_
   registered()`, which imports the REAL `MENU_SECTIONS` data structure,
   confirms the item's `endpoint` matches, confirms `required_roles`
   intersects the real `MANAGER_FAMILY_ROLES` (from `app.route_support`,
   the same set `@manager_required` itself uses), and confirms the
   endpoint is a genuinely live Flask endpoint via `current_app.
   view_functions`. This is a real behavioral check against the actual
   canonical registry and the actual running app, not a string search.

This file proves: (a) the dead literals are gone from `menu_registry.py`'s
raw text, (b) the gate still reports 0 errors for these 4 keys -- now for
a genuine reason, (c) the check function itself is truly behavioral (a
fabricated key that has never existed anywhere returns False; a real key
paired with a wrong endpoint returns False; removing an item from the
real `MENU_SECTIONS` at runtime makes the gate re-report that exact error
-- proving this is not a disguised static pass), and (d) real user-facing
navigation behavior (admin sees all 4 exactly once, `personel` sees none,
auth unchanged) is completely undisturbed by this internal mechanism
change, using the same real, isolated Flask app pattern as every other
contract test in this suite.
"""
from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MENU_REGISTRY_FILE = "app/menu_registry.py"

FOUR_KEYS_AND_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("performance_meeting_development", "main.performance_meeting_development"),
    ("performance_meeting_test_scenarios", "main.performance_meeting_test_scenarios"),
    ("performance_meeting_development_faz3", "main.performance_meeting_development_faz3"),
    ("performance_meeting_final_gate", "main.performance_meeting_final_gate"),
)

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "audit_tmp" / "meeting_dev_nav_fix" / "canonical_source_test_dbs"
_PASSWORD = "MeetingDevCanonicalFixKey1!"


def test_this_file_introduces_no_skip_or_xfail_usage() -> None:
    """Checks for the decorator FORM (start-of-line '@pytest.mark.skip'/
    '@pytest.mark.xfail') rather than a plain substring search, since this
    file's own assertions below legitimately mention those strings inside
    string literals while testing for their absence as decorators."""
    text = Path(__file__).read_text(encoding="utf-8")
    assert re.search(r"^\s*@pytest\.mark\.skip", text, re.MULTILINE) is None
    assert re.search(r"^\s*@pytest\.mark\.xfail", text, re.MULTILINE) is None


@pytest.mark.parametrize("key,endpoint", FOUR_KEYS_AND_ENDPOINTS)
def test_dead_literal_is_gone_from_menu_registry_raw_text(key: str, endpoint: str) -> None:
    """menu_registry.py must no longer contain these keys as raw text at
    all -- proving the gate is no longer (even accidentally) satisfied by
    a text scan of this file."""
    content = (REPO_ROOT / MENU_REGISTRY_FILE).read_text(encoding="utf-8")
    assert key not in content, (
        f"'{key}' still appears as literal text in {MENU_REGISTRY_FILE} -- "
        "the dead FORCE_VISIBLE_MENU_ROLES cleanup was expected to remove it."
    )


def test_legacy_force_visible_dead_literals_are_untouched() -> None:
    """This wave must NOT touch the pre-existing (already-dead, already
    disclosed as LEGACY_DEAD_MENU_LITERAL_DEBT) President Approvals /
    Phase 9 / Phase 10 FORCE_VISIBLE_MENU_ROLES blocks -- scope discipline
    guard."""
    content = (REPO_ROOT / MENU_REGISTRY_FILE).read_text(encoding="utf-8")
    for legacy_key in (
        "performance_president_approvals",
        "performance_meeting_p3_reminders",
        "performance_development_guidance",
    ):
        assert f'FORCE_VISIBLE_MENU_ROLES.setdefault("{legacy_key}"' in content, (
            f"Legacy FORCE_VISIBLE_MENU_ROLES entry for '{legacy_key}' was expected to remain "
            "untouched (separate, disclosed technical debt, out of this wave's scope)."
        )


@pytest.fixture(scope="module")
def canonical_env():
    mp = pytest.MonkeyPatch()
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    mp.setenv("APP_ENV", "testing")
    mp.setenv("FLASK_ENV", "testing")
    mp.setenv("SECRET_KEY", "test-secret-key-for-canonical-menu-source-contract-min-length-ok")
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
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix())

    from app.extensions import db
    from app.services import runtime_schema

    with app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has

    yield app
    mp.undo()


@pytest.mark.parametrize("key,endpoint", FOUR_KEYS_AND_ENDPOINTS)
def test_real_canonical_check_passes_for_each_of_the_four_screens(canonical_env, key: str, endpoint: str) -> None:
    from app.services.performance.meeting_development_final_gate import (
        _menu_item_canonically_registered,
    )

    with canonical_env.app_context():
        assert _menu_item_canonically_registered(key, endpoint) is True


def test_fabricated_key_that_never_existed_anywhere_is_rejected(canonical_env) -> None:
    """A key with zero relationship to any real registry entry must be
    rejected -- proves the check consults real data, not a hardcoded
    allowlist or a text search that could be fooled by an unrelated
    substring somewhere in the repo."""
    from app.services.performance.meeting_development_final_gate import (
        _menu_item_canonically_registered,
    )

    with canonical_env.app_context():
        assert _menu_item_canonically_registered(
            "performance_meeting_totally_fabricated_key_zzz", "main.performance_meeting_development"
        ) is False


@pytest.mark.parametrize("key,endpoint", FOUR_KEYS_AND_ENDPOINTS)
def test_real_key_with_mismatched_endpoint_is_rejected(canonical_env, key: str, endpoint: str) -> None:
    """A real, correctly-registered key must still fail if paired with
    the wrong endpoint -- proves the check verifies the endpoint binding,
    not just key presence."""
    from app.services.performance.meeting_development_final_gate import (
        _menu_item_canonically_registered,
    )

    with canonical_env.app_context():
        assert _menu_item_canonically_registered(key, "main.this_endpoint_does_not_exist_zzz") is False


def test_removing_a_canonical_registration_makes_the_gate_re_fail(canonical_env) -> None:
    """The decisive behavioral proof: if the real canonical registry
    (MENU_SECTIONS) is missing an item at runtime, build_final_gate_
    context() must report an error for exactly that key -- proving 0
    errors is a live, re-derivable fact about current state, not a cached
    or hardcoded pass."""
    import copy

    import app.menu_registry_data_sections as sections_mod
    from app.services.performance.meeting_development_final_gate import build_final_gate_context

    original = sections_mod.MENU_SECTIONS
    patched = copy.deepcopy(original)
    removed_key = "performance_meeting_test_scenarios"
    for section in patched:
        if section.get("key") == "performans":
            section["items"] = [item for item in section["items"] if item.get("key") != removed_key]
    sections_mod.MENU_SECTIONS = patched
    try:
        with canonical_env.app_context():
            ctx = build_final_gate_context()
        assert any(removed_key in e for e in ctx["errors"]), (
            f"Expected an error mentioning '{removed_key}' after removing it from the real "
            f"canonical registry; got errors={ctx['errors']!r}"
        )
        assert ctx["status"] == "KONTROL GEREKİYOR"
    finally:
        sections_mod.MENU_SECTIONS = original


def test_real_gate_reports_zero_errors_for_genuine_behavioral_reasons(canonical_env) -> None:
    """The real, unmocked, current-state check: 0 errors, and specifically
    none of the 4 canonical-menu error messages present."""
    from app.services.performance.meeting_development_final_gate import build_final_gate_context

    with canonical_env.app_context():
        ctx = build_final_gate_context()

    assert ctx["status"] == "GEÇTİ"
    assert ctx["errors"] == []
    assert ctx["warnings"] == []
    assert len(ctx["final_checks"]) == 6
    for key, _endpoint in FOUR_KEYS_AND_ENDPOINTS:
        assert f"Menü kaydı doğrulandı: {key}" in ctx["passed"]
        assert not any(key in e for e in ctx["errors"])


def test_menu_registry_file_no_longer_declared_in_required_tokens() -> None:
    from app.services.performance.meeting_development_final_gate import REQUIRED_TOKENS

    assert MENU_REGISTRY_FILE not in REQUIRED_TOKENS, (
        "app/menu_registry.py should no longer be raw-text scanned by REQUIRED_TOKENS -- "
        "it is not the canonical source for menu item registration."
    )


def test_base_html_remains_a_literal_token_check() -> None:
    """base.html IS the genuine, sole presentation source for these nav
    labels/hrefs -- unlike menu_registry.py, no WRONG_TARGET_FILE issue
    applies here, so this wave must leave it as a literal scan."""
    from app.services.performance.meeting_development_final_gate import REQUIRED_TOKENS

    assert "app/templates/base.html" in REQUIRED_TOKENS
    assert len(REQUIRED_TOKENS["app/templates/base.html"]) == 5
