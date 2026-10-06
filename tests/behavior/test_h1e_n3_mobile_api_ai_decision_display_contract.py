"""BYS360 H1E-N3 -- mobile note-type API + AI decision-support display fixes.

A repo-wide grep audit flagged three raw-value display leaks in this sub-wave's
scope. All three shared the exact same anti-pattern already banned elsewhere
in this initiative: `LABELS.get(raw, raw)` / `raw.replace('_', ' ').title()`
used as the fallback for a value that IS present but is NOT in the label
dictionary -- silently echoing the raw machine code (English or otherwise
unformatted) to the end user instead of a safe, generic Turkish label. Only
that fallback branch changed in each case; the mapping dictionaries, the
existing empty/None-value defaults, function names/signatures, DB columns,
and JSON field names are all untouched.

  1. app/api/mobile/performance_routes.py::
     _bys360_legacy__v2853_note_type_label (despite the "_legacy_" in its
     name, this IS the live implementation -- performance_period_service's
     _v2853_note_type_label() is a thin re-export wrapper calling straight
     back into it). Feeds the mobile Flutter app's note-type label field on
     GET /api/mobile/performance/in-period-notes/v2 (item['status']) and GET
     /api/mobile/performance/note-scorecard (item['meta']). Fallback changed
     from `key.replace('_', ' ').title()` to a plain "Bilinmiyor".

  2. app/api/mobile/services/performance_note_route_services.py, inside
     phase3c_mobile_performance_note_scorecard_v2863a_service's except block
     (the defensive fallback taken if calling _v2853_note_type_label itself
     raises). Fallback changed from
     `str(row.get('note_type') or 'Not').replace('_', ' ').title()` to
     `'Not' if not row.get('note_type') else 'Bilinmiyor'` -- the pre-existing
     empty/None-value default ('Not') is completely untouched; only the
     present-but-something-broke branch no longer echoes the raw DB value.

  3. app/services/ai_decision/interim_feedback_policy.py::
     summarize_interim_notes's `counts_labelled` dict (feeds the Faz 10 AI
     decision-support "Performans İçi Ara Not / Geri Bildirim" breakdown).
     `counts` is keyed by normalize_note_type()'s output, which today is
     always already a member of NOTE_TYPE_LABELS -- so the raw-echo fallback
     is not reachable via the current public call graph, but the anti-pattern
     is fixed defensively/consistently with the rest of this initiative, AND
     because counts_labelled dict KEYS must stay unique (two different
     unmapped codes cannot collide onto the same fallback key and silently
     overwrite each other's counts), the fallback is
     `f"Bilinmiyor ({k})"` (keeps the original code embedded, so it can never
     collide) rather than a bare "Bilinmiyor". Reachability of this branch is
     exercised in tests below by monkeypatching normalize_note_type, which is
     the only way *any* caller (current or future) can land an out-of-domain
     key in `counts`.

NOTE (pre-existing, unrelated bug -- found, NOT fixed, flagged for the
coordinator): app/ai/decision_support_faz10_routes.py defines its own
`ai_decision_faz10_bp` Blueprint and app/ai/routes.py attempts to register it
via `_bys360_parent_bp = globals().get("bp") or globals().get("ai_bp") or
globals().get("ai")` -- but routes.py never defines any module-level name
`bp`, `ai_bp`, or `ai` (it only imports `main_bp` from app.route_registry),
so `_bys360_parent_bp` is always None and `ai_decision_faz10_bp.register_
blueprint(...)` is never reached. Confirmed empirically: booting the full app
and dumping `app.url_map.iter_rules()` shows zero routes containing "faz10"
or "decision-support/faz10" (compare with faz1..faz9, which DO show up, e.g.
"/ai/decision-support/faz9/health"). This means GET /decision-support/faz10/
interim-feedback (and /health) are unreachable dead code in the current app --
not a display-layer bug, and immaterial to this display fix (the underlying
function summarize_interim_notes/build_interim_feedback_decision_support is
still directly callable and correctly exercised in the tests below), so it is
left alone here.

Fixture pattern for the two mobile-API tests: copied from the proven pattern
in tests/behavior/test_mobile_performance_note_creation_authorization_contract.py
(Config class attributes monkeypatched BEFORE create_app(), StaticPool +
pysqlite isolation_level=None + explicit BEGIN event listener, and the real
mobile bearer-token issuance function app.api.mobile.shared._issue_token --
no hand-rolled tokens). Uses its own dedicated tmp DB directory so it shares
no state with any other wave/agent running concurrently in this worktree.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

_TMP_DB_DIR = str(Path(tempfile.gettempdir()) / "bys360_pytest_tmp_h1e_n3")

_PASSWORD = "H1EN3MobileAiContractTest1!"
_FIRST_LOGIN_PASSWORD = "h1e-n3-first-login-test-pw"

_IN_PERIOD_NOTES_ENDPOINT = "/api/mobile/performance/in-period-notes/v2"
_NOTE_SCORECARD_ENDPOINT = "/api/mobile/performance/note-scorecard"

_user_counter = 0


# ---------------------------------------------------------------------------
# A: pure-function unit contracts (no app required).
# ---------------------------------------------------------------------------


def test_bys360_legacy_note_type_label_known_values_map_correctly() -> None:
    from app.api.mobile.performance_routes import _bys360_legacy__v2853_note_type_label

    assert _bys360_legacy__v2853_note_type_label("olumlu_olay") == "Olumlu Olay"
    assert _bys360_legacy__v2853_note_type_label("olumsuz_olay") == "Olumsuz Olay"
    assert _bys360_legacy__v2853_note_type_label("basari") == "Başarı"
    assert _bys360_legacy__v2853_note_type_label("gelisim_ihtiyaci") == "Gelişim İhtiyacı"
    assert _bys360_legacy__v2853_note_type_label("genel_gozlem") == "Genel Gözlem"
    # Case/whitespace-insensitive lookup is pre-existing behavior -- untouched.
    assert _bys360_legacy__v2853_note_type_label("  BASARI  ") == "Başarı"


def test_bys360_legacy_note_type_label_unmapped_value_returns_safe_fallback_never_raw() -> None:
    from app.api.mobile.performance_routes import _bys360_legacy__v2853_note_type_label

    result = _bys360_legacy__v2853_note_type_label("future_note_type_v99")

    assert result == "Bilinmiyor"
    assert result != "future_note_type_v99"
    assert result != "Future Note Type V99"  # the old title-cased raw echo


def test_bys360_legacy_note_type_label_empty_default_is_unchanged() -> None:
    """The pre-existing 'genel_gozlem' empty/None default must stay exactly
    as it was -- only the unmapped-but-present branch was narrowed."""
    from app.api.mobile.performance_routes import _bys360_legacy__v2853_note_type_label

    assert _bys360_legacy__v2853_note_type_label(None) == "Genel Gözlem"
    assert _bys360_legacy__v2853_note_type_label("") == "Genel Gözlem"


def test_v2853_note_type_label_wrapper_still_delegates_to_the_live_function() -> None:
    """performance_period_service._v2853_note_type_label is a thin re-export
    wrapper -- confirm it still round-trips into the same fixed function
    (guards against the wrapper silently drifting from the real
    implementation in the future)."""
    from app.api.mobile.services.performance_period_service import (
        _v2853_note_type_label as wrapper_fn,
    )

    assert wrapper_fn("basari") == "Başarı"
    assert wrapper_fn("future_note_type_v99") == "Bilinmiyor"


# ---------------------------------------------------------------------------
# B: mobile API (Flask test client) contracts for findings 1 and 2.
# ---------------------------------------------------------------------------


def _make_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1e-n3-contract")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", _FIRST_LOGIN_PASSWORD)
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
    db_path = os.path.join(_TMP_DB_DIR, f"h1e_n3_{uuid.uuid4().hex}.sqlite3")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    monkeypatch.setenv("DATABASE_URL", db_uri)

    from app import create_app
    from config import Config

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

    return flask_app


@pytest.fixture
def app(monkeypatch, install_interim_notes_schema):
    flask_app = _make_app(monkeypatch)
    from app.extensions import db

    with flask_app.app_context():
        # The table is Alembic-owned (revision x1f3a9c5e7b2); requests no longer create it.
        install_interim_notes_schema(db.engine)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _next_suffix() -> int:
    global _user_counter
    _user_counter += 1
    return _user_counter


def _create_user(app, *, role="personel", password=_PASSWORD):
    from app.extensions import db
    from app.models import User

    suffix = _next_suffix()
    with app.app_context():
        user = User(
            sicil_no=f"H1EN3{suffix:06d}",
            email=f"h1e-n3-{suffix}@bys360.test",
            ad="H1EN3",
            soyad=f"User{suffix}",
            role=role,
            is_active=True,
            must_change_password=False,
            must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _auth_headers(app, user_id):
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user is not None
        token = _issue_token(user)
        return {"Authorization": f"Bearer {token}"}


def _create_note(client, headers, *, note_type, title, note="H1E-N3 synthetic note", include_in_scorecard=False):
    payload = {
        "note": note,
        "note_type": note_type,
        "title": title,
        "include_in_scorecard": include_in_scorecard,
    }
    return client.post(_IN_PERIOD_NOTES_ENDPOINT, json=payload, headers=headers)


def _stored_note_type(app, note_text):
    from sqlalchemy import text as _sql_text

    from app.extensions import db

    with app.app_context():
        row = db.session.execute(
            _sql_text("SELECT note_type FROM performance_interim_notes WHERE note = :note"),
            {"note": note_text},
        ).first()
        return row[0] if row else None


def _force_note_type_empty_in_db(app, note_text):
    from sqlalchemy import text as _sql_text

    from app.extensions import db

    with app.app_context():
        db.session.execute(
            _sql_text("UPDATE performance_interim_notes SET note_type = '' WHERE note = :note"),
            {"note": note_text},
        )
        db.session.commit()


# --- Finding 1: GET /api/mobile/performance/in-period-notes/v2 -------------


def test_in_period_notes_api_shows_safe_fallback_for_unmapped_note_type(app, client) -> None:
    user_id = _create_user(app)
    headers = _auth_headers(app, user_id)
    note_text = f"UNMAPPED-NOTE-{uuid.uuid4().hex}"

    create_resp = _create_note(
        client, headers, note_type="future_note_type_v99", title="Test Note", note=note_text,
    )
    assert create_resp.status_code == 200

    resp = client.get(_IN_PERIOD_NOTES_ENDPOINT, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None

    matching = [item for item in body.get("items", []) if note_text in item.get("subtitle", "")]
    assert len(matching) == 1
    item = matching[0]

    assert item["status"] == "Bilinmiyor"
    assert item["status"] != "future_note_type_v99"
    assert item["status"] != "Future Note Type V99"

    # (d) underlying stored/DB value is unchanged -- only the display label
    # in the API response differs from the raw DB value.
    assert _stored_note_type(app, note_text) == "future_note_type_v99"


def test_in_period_notes_api_shows_correct_turkish_label_for_known_note_type(app, client) -> None:
    user_id = _create_user(app)
    headers = _auth_headers(app, user_id)
    note_text = f"KNOWN-NOTE-{uuid.uuid4().hex}"

    create_resp = _create_note(
        client, headers, note_type="basari", title="Test Note", note=note_text,
    )
    assert create_resp.status_code == 200

    resp = client.get(_IN_PERIOD_NOTES_ENDPOINT, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()

    matching = [item for item in body.get("items", []) if note_text in item.get("subtitle", "")]
    assert len(matching) == 1
    assert matching[0]["status"] == "Başarı"

    assert _stored_note_type(app, note_text) == "basari"


# --- Finding 2: GET /api/mobile/performance/note-scorecard except-path ------


def test_note_scorecard_except_path_uses_safe_fallback_when_note_type_present(app, client, monkeypatch) -> None:
    user_id = _create_user(app)
    headers = _auth_headers(app, user_id)
    note_text = f"SCORECARD-EXCEPT-NOTE-{uuid.uuid4().hex}"

    # Create the note BEFORE forcing the label function to raise, so
    # creation itself (which also calls the label function for its own
    # title default -- bypassed here via an explicit title) succeeds.
    create_resp = _create_note(
        client, headers, note_type="future_note_type_v99", title="Test Note",
        note=note_text, include_in_scorecard=True,
    )
    assert create_resp.status_code == 200
    assert _stored_note_type(app, note_text) == "future_note_type_v99"

    import app.api.mobile.performance_routes as performance_routes_module

    def _always_raise(_value):
        raise RuntimeError("forced failure for H1E-N3 except-path contract test")

    monkeypatch.setattr(performance_routes_module, "_v2853_note_type_label", _always_raise)

    resp = client.get(_NOTE_SCORECARD_ENDPOINT, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None

    matching = [item for item in body.get("items", []) if note_text in item.get("subtitle", "")]
    assert len(matching) == 1
    meta = matching[0]["meta"]

    assert "Bilinmiyor" in meta
    assert "future_note_type_v99" not in meta
    assert "Future Note Type V99" not in meta

    # (d) the exception in the display layer must not have touched the DB.
    assert _stored_note_type(app, note_text) == "future_note_type_v99"


def test_note_scorecard_except_path_preserves_pre_existing_empty_default(app, client, monkeypatch) -> None:
    """The empty/None-value default ('Not') for this except-path fallback is
    NOT something this fix touched -- confirm it still behaves exactly as
    before even when the label function raises."""
    user_id = _create_user(app)
    headers = _auth_headers(app, user_id)
    note_text = f"SCORECARD-EXCEPT-EMPTY-NOTE-{uuid.uuid4().hex}"

    create_resp = _create_note(
        client, headers, note_type="genel_gozlem", title="Test Note",
        note=note_text, include_in_scorecard=True,
    )
    assert create_resp.status_code == 200

    # The public create API always defaults a falsy note_type to
    # 'genel_gozlem', so the only way to exercise the pre-existing
    # empty-value branch is to force the stored column empty directly.
    _force_note_type_empty_in_db(app, note_text)
    assert _stored_note_type(app, note_text) == ""

    import app.api.mobile.performance_routes as performance_routes_module

    def _always_raise(_value):
        raise RuntimeError("forced failure for H1E-N3 except-path contract test")

    monkeypatch.setattr(performance_routes_module, "_v2853_note_type_label", _always_raise)

    resp = client.get(_NOTE_SCORECARD_ENDPOINT, headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()

    matching = [item for item in body.get("items", []) if note_text in item.get("subtitle", "")]
    assert len(matching) == 1
    meta = matching[0]["meta"]

    assert "Not" in meta
    assert "Bilinmiyor" not in meta


# ---------------------------------------------------------------------------
# C: AI decision-support module (app/services/ai_decision/interim_feedback_
#    policy.py) -- pure-function contracts. No Flask route reaches this
#    function today (see the dead-code note in the module docstring above),
#    so these are exercised directly against summarize_interim_notes(), which
#    takes a plain list of note-like dicts and needs no DB/app context.
# ---------------------------------------------------------------------------


def test_counts_labelled_known_note_types_map_to_turkish_labels() -> None:
    from app.services.ai_decision.interim_feedback_policy import summarize_interim_notes

    notes = [
        {"note_type": "positive_event"},
        {"note_type": "success"},
        {"note_type": "success"},
    ]
    summary = summarize_interim_notes(notes, include_examples=False)
    labelled = summary["counts_labelled"]

    assert labelled.get("Olumlu olay") == 1
    assert labelled.get("Başarı") == 2
    # Raw machine codes must never appear as dict keys.
    assert "positive_event" not in labelled
    assert "success" not in labelled


def test_counts_labelled_unmapped_keys_get_collision_safe_fallback_never_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forces two DIFFERENT out-of-domain note-type codes into `counts` (by
    monkeypatching normalize_note_type, the only seam through which an
    unmapped key could ever reach `counts` today or in the future) and
    proves counts_labelled keeps them as two DISTINCT, non-colliding keys
    instead of silently summing them under one bare fallback string."""
    import app.services.ai_decision.interim_feedback_policy as policy_module

    def _fake_normalize(note_type):
        return str(note_type)

    monkeypatch.setattr(policy_module, "normalize_note_type", _fake_normalize)

    notes = [
        {"note_type": "future_note_type_v99"},
        {"note_type": "future_note_type_v100"},
    ]
    summary = policy_module.summarize_interim_notes(notes, include_examples=False)
    labelled = summary["counts_labelled"]

    assert labelled.get("Bilinmiyor (future_note_type_v99)") == 1
    assert labelled.get("Bilinmiyor (future_note_type_v100)") == 1
    # Two unmapped codes must never collapse onto the same key.
    assert len(labelled) == 2
    assert "future_note_type_v99" not in labelled
    assert "future_note_type_v100" not in labelled

    # (d)-equivalent: the raw, un-relabelled `counts` dict (the actual
    # underlying data, as opposed to the counts_labelled display copy) still
    # holds the real codes untouched.
    assert summary["counts"]["future_note_type_v99"] == 1
    assert summary["counts"]["future_note_type_v100"] == 1


def test_build_interim_feedback_decision_support_surfaces_safe_labels() -> None:
    """Higher-level entry point actually used by the (currently unreachable)
    Faz 10 route -- confirm the fallback survives through the full public
    call chain, not just the innermost dict comprehension."""
    import app.services.ai_decision.interim_feedback_policy as policy_module

    def _fake_normalize(note_type):
        return str(note_type)

    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(policy_module, "normalize_note_type", _fake_normalize)
        notes = [{"note_type": "future_note_type_v99"}]
        result = policy_module.build_interim_feedback_decision_support(notes)
    finally:
        mp.undo()

    labelled = result["summary"]["counts_labelled"]
    assert labelled == {"Bilinmiyor (future_note_type_v99)": 1}
