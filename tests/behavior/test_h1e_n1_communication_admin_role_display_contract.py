"""BYS360 H1E-N1 -- communication + admin + live-surface + role-display.

A fresh repo-wide grep audit found several more raw-value display leaks in
the communication/admin/live-surface/role-display surface area:

  - app/services/communication_phase4_service.py's create_executive_report()
    built the generated report's `title` via
    `report_type.replace('_', ' ').title()` -- report_type is a genuinely
    closed 3-value vocabulary (see app/communication/phase4_routes.py's
    `request.form.get("report_type") or "weekly_summary"` and the
    `<select name="report_type">` in
    app/templates/communication/phase4_reports.html), so an unmapped value
    would have shown raw/title-cased English in the report title forever
    (it is persisted on CommunicationExecutiveReport.title, not recomputed).
    Fixed with a new REPORT_TYPE_LABELS dict + "Bilinmiyor" fallback. The
    stored `report_type` column itself (and the request contract) are
    untouched -- only the generated `title` string changed.

  - Four independently duplicated ~8-value closed role-vocabulary label
    dicts, each falling back to `role.replace('_', ' ').title()` for an
    unmapped value:
      * app/services/hierarchy_rulebook_service.py's role_label()
      * app/services/auto_hierarchy_service.py's ImportError-fallback copy
        of personnel_sync_service.canonical_role_label (normally shadowed
        by a working import -- personnel_sync_service has no import cycle
        with this module, so the fallback is defensive/dead code today,
        but it still carried the same anti-pattern)
      * app/services/communication_phase1_service.py's
        manager_filter_options() (builds a filter-dropdown (value, label)
        tuple list)
      * app/services/performance_v2/chain.py's _humanize_role()
    No existing *already-correct* reusable helper covers this exact closed
    vocabulary safely: app/services/personnel_sync_service.py's
    canonical_role_label() is used elsewhere in the repo but its own
    unmapped-fallback echoes the raw value verbatim
    (`str(raw_role or "Personel").strip() or "Personel"`), and
    app/services/ai/visibility_gate.py's _role_label() /
    app/services/communication_phase5_service.py's role_label() are two
    MORE independent duplicates of this same dict elsewhere in the repo
    (out of this wave's scope -- other files, noted for the coordinator,
    not fixed here). So a new single shared source,
    app/services/role_display.py (ROLE_DISPLAY_LABELS dict +
    UNKNOWN_ROLE_DISPLAY_LABEL="Bilinmiyor" + role_display_label()), was
    added and all four in-scope call sites now import the dict from it
    instead of keeping their own copy. Each call site's own pre-existing
    *empty/missing-value* handling (hierarchy_rulebook_service.role_label
    returns "" for empty input; auto_hierarchy_service's fallback defaults
    to the "personel" role business default; communication_phase1_service
    skips empty roles entirely via `if role and ...`; performance_v2's
    _humanize_role falls back to the manager's own unvan/role_label/role
    text) is completely untouched -- only the "value present but
    unmapped" branch now returns "Bilinmiyor" instead of an echoed/
    title-cased raw string.

  - app/services/live_surface_service.py's _area_label()/_removed_label()
    fell back to `str(key or '').replace('_', ' ').title()` for a key not
    in their (small, closed) _AREA_LABELS/_REMOVED_LABELS dicts. Fixed to
    "Bilinmiyor" for a genuinely unmapped, non-empty key; the existing
    empty-input fallback ("") is unchanged, and the dicts themselves are
    untouched.

  - app/main_handlers/account_visibility_helpers.py had four
    `label_map.get(key, key)` sites (menu-key -> display-label lookups
    feeding an admin visibility-rule preview/export screen). Three of
    them (_list_settings_template_archives, _save_settings_template_archive,
    _build_user_visibility_diff) build `label_map` from the SAME
    `flat_menu_items` argument that also bounds every `key` they ever look
    up, so the miss branch is provably unreachable through any current
    caller -- fixed anyway (Bilinmiyor instead of echoing `key`) as a
    defensive/negative-test-gap closure, matching the precedent already
    established by
    tests/behavior/test_h1e_systemic_self_fallback_residual_contract.py
    for the same shape of "currently inert but still worth hardening"
    fix, so NOT given a dedicated reachability test here (there would be
    no way to make it fail before the fix and pass after without
    fabricating a scenario the real code can never produce). The fourth,
    `_build_visibility_template_payload()` (used by the "Ayarlar" ->
    dışa aktar visibility-template export, POST /settings with
    form_action=export_visibility_template), genuinely CAN diverge: its
    `effective_rule_map` comes from build_effective_user_menu_context(),
    which folds in raw UserMenuPermission override rows without
    filtering them against the live flat_menu_items list (only a
    "known-removed-module" filter is applied there, not a "known
    key exists" filter) -- so a stale/renamed menu key with a user
    override row IS a real, reachable path to the fallback branch. Both
    a direct unit-level call and a full POST /settings route test cover
    this one.

  - app/services/communication_phase9c_service.py:376's
    `INCIDENT_SEVERITY_LABELS.get(severity, severity)` was re-checked and
    remains a confirmed FALSE POSITIVE: `severity` is clamped to a value
    already known to be in INCIDENT_SEVERITY_LABELS a few lines earlier
    (`if severity not in INCIDENT_SEVERITY_LABELS: severity = 'medium'`),
    so the echo-fallback branch is mechanically unreachable. Left
    untouched, no test needed (nothing changed there).

Writes NOTHING to any production source file -- only to its own isolated,
temporary SQLite DB.
"""
from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1e_n1_comm_admin_role_display_tmp" / "test_dbs"
_PASSWORD = "H1EN1CommAdminRoleDisplayTest1!"


# ---------------------------------------------------------------------------
# A: pure-function unit contracts (no app required).
# ---------------------------------------------------------------------------


def test_role_display_shared_source_never_leaks_raw() -> None:
    from app.services.role_display import (
        ROLE_DISPLAY_LABELS,
        UNKNOWN_ROLE_DISPLAY_LABEL,
        role_display_label,
    )

    assert ROLE_DISPLAY_LABELS["baskan"] == "Başkan"
    assert ROLE_DISPLAY_LABELS["baskan_yardimcisi"] == "Başkan Yardımcısı"
    assert ROLE_DISPLAY_LABELS["hukuk_musaviri"] == "Hukuk Müşaviri"
    assert UNKNOWN_ROLE_DISPLAY_LABEL == "Bilinmiyor"

    assert role_display_label("mali_musavir") == "Mali Müşavir"
    assert role_display_label("future_role_v99") == "Bilinmiyor"
    assert role_display_label("future_role_v99") != "Future Role V99"
    assert role_display_label(None) == "Bilinmiyor"


def test_hierarchy_rulebook_role_label_never_leaks_raw() -> None:
    from app.services.hierarchy_rulebook_service import role_label

    assert role_label("baskan") == "Başkan"
    assert role_label("koordinator") == "Koordinatör"
    assert role_label("future_role_v99") == "Bilinmiyor"
    assert role_label("future_role_v99") != "Future Role V99"
    # Empty-input fallback predates this fix and must stay exactly as it was.
    assert role_label("") == ""


def test_performance_v2_chain_humanize_role_never_leaks_raw() -> None:
    from app.services.performance_v2.chain import _humanize_role

    manager = SimpleNamespace(unvan="Uzman Yardımcısı", role_label=None, role="personel")

    assert _humanize_role("baskan", manager) == "Başkan"
    assert _humanize_role("hukuk_musaviri", manager) == "Hukuk Müşaviri"
    assert _humanize_role("future_role_v99", manager) == "Bilinmiyor"
    assert _humanize_role("future_role_v99", manager) != "Future Role V99"
    # A falsy role_token's fallback (manager's own unvan/role_label/role text)
    # predates this fix and must stay exactly as it was.
    assert _humanize_role(None, manager) == "Uzman Yardımcısı"
    assert _humanize_role("", manager) == "Uzman Yardımcısı"


def test_live_surface_area_and_removed_labels_never_leak_raw() -> None:
    from app.services.live_surface_service import _area_label, _removed_label

    assert _area_label("performance") == "Performans Yönetimi"
    assert _area_label("future_area_v9") == "Bilinmiyor"
    assert _area_label("future_area_v9") != "Future Area V9"
    # Empty-input fallback predates this fix and must stay exactly as it was.
    assert _area_label("") == ""
    assert _area_label(None) == ""  # type: ignore[arg-type]  # runtime tolerates None defensively despite the `str` type hint

    assert _removed_label("portal") == "İç Portal"
    assert _removed_label("future_removed_v9") == "Bilinmiyor"
    assert _removed_label("") == ""


def test_report_type_labels_never_leak_raw() -> None:
    from app.services.communication_phase4_service import REPORT_TYPE_LABELS

    assert REPORT_TYPE_LABELS["weekly_summary"] == "Haftalık Özet"
    assert REPORT_TYPE_LABELS["executive_brief"] == "Yönetici Brifi"
    assert REPORT_TYPE_LABELS["scorecard"] == "Skor Kartı"
    assert REPORT_TYPE_LABELS.get("future_report_type_v9", "Bilinmiyor") == "Bilinmiyor"


def test_auto_hierarchy_import_fallback_role_label_never_leaks_raw() -> None:
    """app/services/auto_hierarchy_service.py wraps its primary
    `from app.services.personnel_sync_service import canonical_role_label,
    canonical_role_value` in a `try/except Exception`, redefining a local
    fallback pair for the case that import ever fails. personnel_sync_service
    has no import cycle back to auto_hierarchy_service (confirmed by
    grep), so in this repo the fallback is normally shadowed by the
    successful import and never actually runs -- but it still shipped the
    same `role.replace('_', ' ').title()` anti-pattern for an unmapped
    role. This loads a throwaway, separately-named copy of the module
    (via importlib, from the SAME source file) with
    app.services.personnel_sync_service sentinel-blocked in sys.modules
    for that one load, forcing the except branch to execute, WITHOUT
    touching the real, already-imported app.services.auto_hierarchy_service
    module that routes/other tests depend on. sys.modules mutations are
    done through monkeypatch.setitem so they are automatically reverted at
    teardown regardless of outcome.
    """
    import importlib.util
    import sys

    # Ensure both real modules are already fully loaded/cached under their
    # real names before we sentinel-block personnel_sync_service -- so the
    # fresh module's own `from app.services.hierarchy_rulebook_service
    # import (...)` line (which itself needs personnel_sync_service) is
    # satisfied from the cache instead of re-executing and tripping on our
    # sentinel.
    import app.services.hierarchy_rulebook_service  # noqa: F401
    import app.services.personnel_sync_service as real_personnel_sync_service

    real_spec = importlib.util.find_spec("app.services.auto_hierarchy_service")
    assert real_spec is not None and real_spec.origin

    fake_module_name = "h1e_n1_test_only_auto_hierarchy_import_fallback_copy"
    spec = importlib.util.spec_from_file_location(fake_module_name, real_spec.origin)
    assert spec is not None and spec.loader is not None
    fresh_module = importlib.util.module_from_spec(spec)

    original_pss = sys.modules.get("app.services.personnel_sync_service")
    try:
        sys.modules["app.services.personnel_sync_service"] = None  # type: ignore[assignment]
        sys.modules[fake_module_name] = fresh_module
        spec.loader.exec_module(fresh_module)
    finally:
        sys.modules.pop(fake_module_name, None)
        if original_pss is not None:
            sys.modules["app.services.personnel_sync_service"] = original_pss
        else:
            sys.modules.pop("app.services.personnel_sync_service", None)

    assert real_personnel_sync_service is sys.modules["app.services.personnel_sync_service"]

    # The except-branch fallback pair is now bound on the fresh module.
    assert fresh_module.canonical_role_label("baskan") == "Başkan"
    assert fresh_module.canonical_role_label("future_role_v99") == "Bilinmiyor"
    assert fresh_module.canonical_role_label("future_role_v99") != "Future Role V99"
    # canonical_role_value's own empty-input default ("personel") predates
    # this fix and must stay exactly as it was.
    assert fresh_module.canonical_role_label(None) == "Personel"
    assert fresh_module.canonical_role_value(None) == "personel"


# ---------------------------------------------------------------------------
# B: app/DB-backed contracts.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-n1-comm-admin-role-display-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1e-n1-comm-admin-role-display-first-login-test-pw")
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


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, *, sicil_no, role="admin", password=_PASSWORD, menu_keys=()):
    from app.extensions import db
    from app.models import User, UserMenuPermission

    with app.app_context():
        user = User(
            sicil_no=sicil_no,
            email=f"{sicil_no}@ktb.gov.tr",
            ad="H1E N1",
            soyad="CommAdminRoleDisplayContract",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        for menu_key in menu_keys:
            db.session.add(UserMenuPermission(user_id=user.id, menu_key=menu_key, is_visible=True, source_type="user_override"))
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" not in response.headers.get("Location", "")
    return response


def test_manager_filter_options_role_label_never_leaks_raw(app) -> None:
    from app.services.communication_phase1_service import manager_filter_options

    _create_user(app, sicil_no="h1e_n1_mfo_known", role="baskan")
    _create_user(app, sicil_no="h1e_n1_mfo_unmapped", role="future_role_v99")

    with app.app_context():
        options = manager_filter_options()
        roles = dict(options["roles"])

    assert roles.get("baskan") == "Başkan"
    # The raw role CODE is preserved verbatim as the dropdown value (first
    # tuple element / dict key) -- only the LABEL (second element) changed.
    assert "future_role_v99" in roles
    assert roles["future_role_v99"] == "Bilinmiyor"
    assert roles["future_role_v99"] != "Future Role V99"


def test_create_executive_report_title_uses_turkish_label_and_preserves_stored_report_type(app) -> None:
    from app.models import User
    from app.services.communication_phase4_service import create_executive_report

    actor_id = _create_user(app, sicil_no="h1e_n1_report_actor")

    with app.app_context():
        actor = User.query.get(actor_id)

        known_row = create_executive_report(actor, report_type="scorecard", days=30)
        assert "Skor Kartı" in known_row.title
        assert known_row.report_type == "scorecard"

        unmapped_row = create_executive_report(actor, report_type="future_report_type_v9", days=30)
        assert "Bilinmiyor" in unmapped_row.title
        assert "future_report_type_v9" not in unmapped_row.title
        assert "Future Report Type V9" not in unmapped_row.title
        # The stored report_type column is untouched by the display fix.
        assert unmapped_row.report_type == "future_report_type_v9"


def test_report_create_route_shows_turkish_title_for_known_and_unmapped_report_type(app, client) -> None:
    _create_user(app, sicil_no="h1e_n1_report_route", menu_keys=("reports",))
    _login(client, "h1e_n1_report_route")

    known_resp = client.post(
        "/communication/faz4/reports/create",
        data={"report_type": "executive_brief"},
        follow_redirects=True,
    )
    assert known_resp.status_code == 200
    known_body = known_resp.get_data(as_text=True)
    assert "Yönetici Brifi" in known_body
    assert "executive_brief" not in known_body

    unmapped_resp = client.post(
        "/communication/faz4/reports/create",
        data={"report_type": "future_report_type_v9"},
        follow_redirects=True,
    )
    assert unmapped_resp.status_code == 200
    unmapped_body = unmapped_resp.get_data(as_text=True)
    assert "Bilinmiyor" in unmapped_body
    assert "future_report_type_v9" not in unmapped_body
    assert "Future Report Type V9" not in unmapped_body


def test_build_visibility_template_payload_labels_unmapped_menu_key_as_bilinmiyor(app) -> None:
    """app/main_handlers/account_visibility_helpers.py's
    _build_visibility_template_payload() accepts an already-resolved
    `selected_profile_resolution` dict (the production caller,
    _handle_export_visibility_template(), builds one via
    build_effective_user_menu_context() and passes it through) -- calling
    it directly with a manufactured resolution containing a menu key that
    is not in the live menu registry exercises the real, reachable branch
    without needing a full HTTP round trip (see the route-level test below
    for that)."""
    from app.main_handlers.account_visibility_helpers import (
        _build_visibility_template_payload,
        flatten_settings_menu_definitions,
    )
    from app.models import User

    user_id = _create_user(app, sicil_no="h1e_n1_avh_payload")

    with app.app_context():
        user = User.query.get(user_id)
        flat_menu_items = flatten_settings_menu_definitions()
        fake_resolution = {"effective_rule_map": {"future_menu_key_v9": True}}

        payload = _build_visibility_template_payload(user, flat_menu_items, fake_resolution)

    assert payload["labels"]["future_menu_key_v9"] == "Bilinmiyor"
    assert payload["labels"]["future_menu_key_v9"] != "Future Menu Key V9"
    # The raw machine menu key itself is preserved unchanged -- only its
    # display label is replaced.
    assert payload["effective_rule_map"]["future_menu_key_v9"] is True
    assert "future_menu_key_v9" in payload["visible_keys"]


def test_settings_export_visibility_template_route_labels_stale_menu_key_as_bilinmiyor(app, client) -> None:
    """Full route-level proof for the one reachable
    account_visibility_helpers.py site: a UserMenuPermission override row
    referencing a menu key no longer present in the live menu registry
    (e.g. renamed/removed since the rule was saved) is NOT filtered out by
    filter_live_menu_rows() (that only screens out a small set of
    known-removed MODULES, not "any key absent from today's registry"), so
    it really does reach build_effective_user_menu_context()'s
    effective_rule_map and, from there,
    _build_visibility_template_payload()'s labels dict."""
    from app.extensions import db
    from app.models import UserMenuPermission

    user_id = _create_user(app, sicil_no="h1e_n1_avh_route", role="admin")

    with app.app_context():
        db.session.add(
            UserMenuPermission(user_id=user_id, menu_key="future_menu_key_v9", is_visible=True, source_type="user_override")
        )
        db.session.commit()

    _login(client, "h1e_n1_avh_route")

    response = client.post(
        "/settings",
        data={"form_action": "export_visibility_template", "user_id": str(user_id)},
        follow_redirects=False,
    )
    assert response.status_code == 200
    payload = json.loads(response.get_data(as_text=True))

    assert payload["labels"]["future_menu_key_v9"] == "Bilinmiyor"
    assert payload["labels"]["future_menu_key_v9"] != "Future Menu Key V9"
    # The stale menu key itself is preserved verbatim in the exported
    # machine data -- only its display label is a safe fallback.
    assert "future_menu_key_v9" in payload["effective_rule_map"]
