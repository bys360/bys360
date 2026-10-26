"""BYS360 H1F -- final fresh residual audit (coordinator-level), service-layer
findings not covered by any of the 3 H1F-A/B/C agent waves.

A repo-wide re-scan of app/services/** (not limited to files the agents had
already touched) found further genuine CONFIRMED_USER_VISIBLE_EXCEPTION_LEAK
sites, each traced all the way to its actual rendering surface before being
classified (several superficially similar sites were traced and found to be
FALSE_POSITIVE -- computed but never rendered -- and are documented, not
"fixed", in the coordinator's final report rather than here).

Fixed here:
  - app/services/weather_recommendation_service.py -- the home page's own
    weather widget (templates/home.html renders `weather.message` twice)
    embedded a raw urllib/JSON exception in that message. This is arguably
    the single highest-reach leak found in the whole H1F effort: it would
    have surfaced on the app's own home page for every logged-in user.
  - app/services/sp1d_target_management_service.py -- KPI/target create and
    update, flashed directly by app/performance/sp1_sidebar_routes.py.
  - app/services/sp3a_kpi_dashboard_live_service.py -- KPI dashboard's own
    empty-state fallback (data_note/ai_notes), same shape as the
    ai_agent/dashboard_kpi_bridge.py fix below.
  - app/services/performance/process_engine_phase6_president_approvals.py --
    delete_president_approval_record's failure path, flashed directly by
    app/performance/process_engine_phase6_president_approvals_routes.py.
  - app/services/ai/client.py -- the AI stub-fallback wrapper appended a raw
    network/parsing exception directly onto the AI-generated response TEXT
    itself (not just a side-channel field) whenever the real provider was
    unreachable and AI_ALLOW_STUB_FALLBACK was on.
  - app/services/ai_agent/dashboard_kpi_bridge.py -- KPI assistant summary's
    empty-state fallback (data_note/briefing_notes).
  - app/services/messages/comments.py -- create_message_comment's JSON error
    response.
  - app/services/cic/config_context.py -- Corporate Information Center daily
    weather widget's own unavailable-data message.
  - app/services/cic/mail_service.py -- _cic_v11_send_email_direct's SMTP
    failure detail, persisted into MailLog.error_message (the same
    established "raw exception written into a mail log later rendered on an
    admin mail-logs screen" shape H1F-C already fixed for mail_core.py and
    file_center/mail_service.py, but this is an independent SMTP-calling
    function that wasn't part of that fix).
  - app/services/assistant_role_matrix_v10.py -- Virtual Assistant role
    matrix save failure, flashed directly.
  - app/services/performance/feedback_pipeline.py -- an admin-facing
    "Geri Bildirim Pipeline" diagnostic screen renders every string in its
    `warnings` list verbatim (templates/performance/feedback_pipeline.html
    `{% for w in warnings %}`).

Writes NOTHING to any production source file -- only calls the fixed
functions directly (with dependencies monkeypatched to raise a sentinel
exception) or, where Flask context is required (flash/current_app.logger),
uses `app.test_request_context()`.
"""
from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path

import pytest

from tests.sqlite_test_cleanup import release_sqlite_app

_SENTINEL = "TECHNICAL_SENTINEL_DO_NOT_SHOW_9F3A"


def _raise_sentinel(*_args, **_kwargs):
    raise Exception(_SENTINEL)  # noqa: TRY002 - deliberately generic


_TEST_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "h1f_final_audit_service_layer_tmp" / "test_dbs"


@pytest.fixture
def app(monkeypatch, request):
    _TEST_DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3"

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("FLASK_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-h1f-final-audit-service-layer")
    monkeypatch.setenv("DEFAULT_FIRST_LOGIN_PASSWORD", "h1f-final-audit-service-layer-first-login-test-pw")
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
    request.addfinalizer(lambda: release_sqlite_app(app))
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI="sqlite:///" + db_path.as_posix())

    from app.extensions import db

    with app.app_context():
        db.create_all()

    return app


# ---------------------------------------------------------------------------
# weather_recommendation_service.py -- the home page's own weather widget.
# ---------------------------------------------------------------------------


def test_home_weather_fetch_failure_never_leaks_raw_exception(monkeypatch, caplog) -> None:
    from urllib.error import URLError

    import app.services.weather_recommendation_service as weather_mod

    def _raise_url_error(*_a, **_k):
        raise URLError(_SENTINEL)

    monkeypatch.setattr(weather_mod, "_fetch_open_meteo", _raise_url_error)

    with caplog.at_level(logging.ERROR, logger="app.services.weather_recommendation_service"):
        result = weather_mod.get_home_weather_context(force_refresh=True)

    assert _SENTINEL not in str(result)
    assert result["message"] == "Hava durumu servisi şu an yanıt vermedi."
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# sp1d_target_management_service.py
# ---------------------------------------------------------------------------


def test_sp1d_create_target_failure_never_leaks_raw_exception(monkeypatch) -> None:
    import app.services.sp1d_target_management_service as sp1d_mod

    class _FakeSession:
        def execute(self, *a, **k):
            raise Exception(_SENTINEL)  # noqa: TRY002

        def rollback(self):
            pass

    monkeypatch.setattr(sp1d_mod, "db", type("_D", (), {"session": _FakeSession()})())

    valid_form = {
        "target_code": "T-1",
        "target_name": "Test Hedefi",
        "target_value": "10",
        "weight": "5",
    }
    ok, message = sp1d_mod.create_target_from_form(valid_form, current_user=None)

    assert ok is False
    assert _SENTINEL not in message
    assert message == "Kayıt oluşturulamadı."


# ---------------------------------------------------------------------------
# sp3a_kpi_dashboard_live_service.py
# ---------------------------------------------------------------------------


def test_sp3a_kpi_dashboard_query_failure_never_leaks_raw_exception(monkeypatch, caplog) -> None:
    import app.services.sp3a_kpi_dashboard_live_service as sp3a_mod

    class _FakeSession:
        def execute(self, *a, **k):
            raise Exception(_SENTINEL)  # noqa: TRY002

    monkeypatch.setattr(sp3a_mod, "_first_existing_table", lambda candidates: "kpi_targets")
    monkeypatch.setattr(sp3a_mod, "_safe_columns", lambda table_name: {"id", "target_name"})
    monkeypatch.setattr(sp3a_mod, "db", type("_D", (), {"session": _FakeSession()})())

    with caplog.at_level(logging.ERROR, logger="app.services.sp3a_kpi_dashboard_live_service"):
        context = sp3a_mod.build_sp3a_kpi_dashboard_context(current_user=None)

    assert _SENTINEL not in str(context)
    assert context["data_note"] == "KPI verisi okunurken sorun oluştu."
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# process_engine_phase6_president_approvals.py
# ---------------------------------------------------------------------------


def test_delete_president_approval_record_db_failure_never_leaks_raw_exception(app, monkeypatch, caplog) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    import app.services.performance.process_engine_phase6_president_approvals as p6_mod

    def _raise_sqlalchemy(*_a, **_k):
        raise SQLAlchemyError(_SENTINEL)

    class _FakeMappingsResult:
        def mappings(self):
            return self

        def first(self):
            return {"id": 1}

    class _FakeSession:
        def execute(self, *a, **k):
            return _FakeMappingsResult()

        def commit(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr(p6_mod, "can_delete_president_approval_records", lambda actor: True)
    monkeypatch.setattr(p6_mod, "table_exists", lambda name: name == "performance_president_approvals")
    monkeypatch.setattr(p6_mod, "db", type("_D", (), {"session": _FakeSession()})())
    monkeypatch.setattr(p6_mod, "_delete_from_table_where", _raise_sqlalchemy)

    _p6_logger = "app.services.performance.process_engine_phase6_president_approvals"
    with app.test_request_context("/"), caplog.at_level(logging.ERROR, logger=_p6_logger):
        result = p6_mod.delete_president_approval_record(1, actor=None)

    assert result.ok is False
    assert _SENTINEL not in result.message
    assert result.message == "Kayıt silinemedi."
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# ai/client.py -- stub-fallback wrapper.
# ---------------------------------------------------------------------------


def test_ai_client_stub_fallback_never_appends_raw_exception_to_response_text(app, caplog) -> None:
    from urllib.error import URLError

    from app.services.ai.client import BaseAIClient, _WrappedClient

    class _FailingInner(BaseAIClient):
        def generate(self, *, system_prompt, user_prompt, prompt_version=None):
            raise URLError(_SENTINEL)

    with app.test_request_context("/"):
        app.config["AI_ALLOW_STUB_FALLBACK"] = True
        wrapper = _WrappedClient(_FailingInner())
        with caplog.at_level(logging.ERROR, logger="app.services.ai.client"):
            result = wrapper.generate(system_prompt="s", user_prompt="u")

    assert _SENTINEL not in result.text
    assert _SENTINEL not in (result.error_message or "")
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# ai_agent/dashboard_kpi_bridge.py
# ---------------------------------------------------------------------------


def test_dashboard_kpi_summary_query_failure_never_leaks_raw_exception(monkeypatch, caplog) -> None:
    import app.services.ai_agent.dashboard_kpi_bridge as bridge_mod

    monkeypatch.setattr(bridge_mod, "table_exists", lambda *a, **k: True)
    monkeypatch.setattr(bridge_mod, "table_columns", lambda *a, **k: {"id", "target_name"})
    monkeypatch.setattr(bridge_mod, "has_performance_overview_permission", lambda user: True)

    class _FakeSession:
        def execute(self, *a, **k):
            raise Exception(_SENTINEL)  # noqa: TRY002

    monkeypatch.setattr(bridge_mod, "db", type("_D", (), {"session": _FakeSession()})())

    with caplog.at_level(logging.ERROR, logger="app.services.ai_agent.dashboard_kpi_bridge"):
        result = bridge_mod.build_dashboard_kpi_summary_for_user(user=None)

    assert _SENTINEL not in str(result)
    assert result["data_note"] == "KPI/Hedef verisi okunurken güvenli boş durum üretildi."
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# messages/comments.py
# ---------------------------------------------------------------------------


def test_create_message_comment_db_failure_never_leaks_raw_exception(app, monkeypatch, caplog) -> None:
    from types import SimpleNamespace

    import app.services.messages.comments as comments_mod

    fake_message = SimpleNamespace(id=1, is_deleted=False, thread_id=7, sender_user_id=None)

    class _FakeSession:
        def get(self, *a, **k):
            return fake_message

        def add(self, *a, **k):
            raise Exception(_SENTINEL)  # noqa: TRY002

        def rollback(self):
            pass

    monkeypatch.setattr(comments_mod, "db", type("_D", (), {"session": _FakeSession()})())
    monkeypatch.setattr(comments_mod, "orm_entity", lambda *a, **k: object)
    monkeypatch.setattr(comments_mod, "participant_for_thread", lambda *a, **k: SimpleNamespace(id=1))
    monkeypatch.setattr(comments_mod, "current_user", SimpleNamespace(id=99))

    with app.test_request_context("/"), caplog.at_level(logging.ERROR, logger="app.services.messages.comments"):
        payload, status = comments_mod.create_message_comment(1, "body", now=None)

    assert status == 500
    assert _SENTINEL not in payload["message"]
    assert payload["message"] == "Yorum eklenirken hata oluştu."
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# cic/config_context.py -- Corporate Information Center weather widget.
# ---------------------------------------------------------------------------


def test_cic_weather_context_failure_never_leaks_raw_exception(monkeypatch, caplog) -> None:
    import app.services.cic.config_context as cic_mod

    monkeypatch.setattr(cic_mod, "get_config", lambda: {"latitude": "40.15", "longitude": "26.41"})

    def _raise_sentinel_urlopen(*_a, **_k):
        raise Exception(_SENTINEL)  # noqa: TRY002

    monkeypatch.setattr(cic_mod, "urlopen", _raise_sentinel_urlopen)

    with caplog.at_level(logging.ERROR, logger="app.services.cic.config_context"):
        result = cic_mod._weather()

    assert _SENTINEL not in str(result)
    assert result["bugun_hava"] == "Güncel hava durumu verisi şu anda alınamadı."
    assert any(r.exc_info and _SENTINEL in str(r.exc_info[1]) for r in caplog.records)


# ---------------------------------------------------------------------------
# assistant_role_matrix_v10.py
# ---------------------------------------------------------------------------


def test_assistant_role_matrix_save_source_no_longer_leaks_raw_exception() -> None:
    import pathlib

    project_root = pathlib.Path(__file__).resolve().parents[2]
    source = (project_root / "app" / "services" / "assistant_role_matrix_v10.py").read_text(encoding="utf-8")
    assert 'flash(f"Sanal Asistan Rol Matrisi kaydedilemedi: {exc}"' not in source
    assert 'flash("Sanal Asistan Rol Matrisi kaydedilemedi."' in source


# ---------------------------------------------------------------------------
# feedback_pipeline.py -- rendered verbatim on an admin diagnostic screen.
# ---------------------------------------------------------------------------


def test_feedback_pipeline_table_status_db_failure_never_leaks_raw_exception(monkeypatch, caplog) -> None:
    import app.services.performance.feedback_pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_project_root", _raise_sentinel)

    with caplog.at_level(logging.ERROR, logger="app.services.performance.feedback_pipeline"):
        items, missing = pipeline_mod._table_status(("some_table",))

    assert items == []
    assert missing == ["Veritabanı kontrolü çalıştırılamadı."]
    assert _SENTINEL not in str(missing)
