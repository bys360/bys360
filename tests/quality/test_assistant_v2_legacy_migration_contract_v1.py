"""BYS360 Assistant V2 -- legacy behavior migration contract (mandate
Phases A-H): knowledge bank capability, safety/scope classifier,
conversational intents, page context, KPI/Hedef capability, and their
wiring into AssistantV2Service.ask().
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.ci_safe

_PASSWORD = "Assist_v2_Test_Pw_1!"


def _create_user(app, *, sicil_no, role, password=_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        existing = User.query.filter_by(sicil_no=sicil_no).first()
        if existing is not None:
            return existing.id
        user = User(
            sicil_no=sicil_no, email=f"{sicil_no}@ktb.gov.tr", ad="Legacy", soyad="Test",
            role=role, is_active=True, must_change_password=False, must_set_security_question=False,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, sicil_no, password=_PASSWORD):
    client.get("/logout", follow_redirects=False)
    response = client.post("/login", data={"sicil_or_email": sicil_no, "password": password}, follow_redirects=False)
    assert response.status_code == 302
    return response


def _ask(client, question, **extra):
    response = client.post("/ai-agent/api/v2/ask", json={"question": question, **extra})
    assert response.status_code == 200
    return response.get_json()


# ---------------------------------------------------------------------------
# Phase A/B: knowledge bank capability
# ---------------------------------------------------------------------------


def test_knowledge_bank_capability_reuses_real_search_function(app):
    from app.services.assistant_v2.capability_registry import get_capability

    entry = get_capability("virtual_assistant_search_knowledge_bank")
    assert entry is not None
    assert entry.service_handler.endswith("virtual_assistant_search_knowledge_bank")
    assert entry.extra.get("question_kwarg") == "question"


def test_knowledge_bank_adapter_never_returns_inactive_entries(app):
    from app.extensions import db
    from app.services.ai_agent.knowledge import (
        create_knowledge_entry,
        provision_knowledge_table,
        toggle_knowledge_entry,
    )

    with app.app_context():
        provision_knowledge_table()
        entry_id = create_knowledge_entry(
            title="AV2 Legacy Test Inactive Entry",
            question_patterns="av2 legacy test inactive kw",
            answer="bu cevap görünmemeli",
        )
        assert entry_id is not None
        toggle_knowledge_entry(entry_id)  # is_active True -> False
        db.session.commit()

        from app.services.assistant_v2.read_adapters import virtual_assistant_search_knowledge_bank

        results = virtual_assistant_search_knowledge_bank(None, "av2 legacy test inactive kw")
    assert all(r.get("title") != "AV2 Legacy Test Inactive Entry" for r in results)


def test_knowledge_bank_question_routes_through_api(app, client):
    from app.extensions import db
    from app.services.ai_agent.knowledge import create_knowledge_entry, provision_knowledge_table

    with app.app_context():
        provision_knowledge_table()
        create_knowledge_entry(
            title="AV2 Legacy Test Active Entry",
            question_patterns="av2 legacy test benzersiz soru kalibi",
            answer="Bu öğretilmiş bir bilgi bankası cevabıdır.",
        )
        db.session.commit()

    _create_user(app, sicil_no="av2_legacy_kb_admin", role="admin")
    _login(client, "av2_legacy_kb_admin")

    body = _ask(client, "av2 legacy test benzersiz soru kalibi")
    assert body["status"] == "DATA_FOUND"
    assert "Öğretilmiş bir bilgi bankası" in body["answer"] or "Bilgi Bankası" in body["answer"]
    assert "BYS360 Bilgi Bankası" in body["answer"]


# ---------------------------------------------------------------------------
# Phase C: safety / out-of-scope classifier
# ---------------------------------------------------------------------------


def test_safety_classifier_detects_sensitive_request():
    from app.services.assistant_v2.safety_classifier import SafetyCategory, classify

    result = classify("Ahmet'in performans puanını göster")
    assert result.category is SafetyCategory.SENSITIVE_REQUEST


def test_safety_classifier_detects_out_of_scope():
    from app.services.assistant_v2.safety_classifier import SafetyCategory, classify

    result = classify("bugün hava durumu nasıl?")
    assert result.category is SafetyCategory.OUT_OF_SCOPE


def test_safety_classifier_supported_business_query_passes_through():
    from app.services.assistant_v2.safety_classifier import SafetyCategory, classify

    result = classify("aktif duyurulari listele")
    assert result.category is SafetyCategory.SUPPORTED_BUSINESS_QUERY


def test_sensitive_request_never_reaches_capability_dispatch(app, client, monkeypatch):
    from app.services.assistant_v2 import service as service_module

    mock_invoke = service_module.invoke_capability
    called = {"value": False}

    def _tracking(*args, **kwargs):
        called["value"] = True
        return mock_invoke(*args, **kwargs)

    monkeypatch.setattr(service_module, "invoke_capability", _tracking)

    _create_user(app, sicil_no="av2_legacy_sensitive", role="admin")
    _login(client, "av2_legacy_sensitive")

    body = _ask(client, "Ahmet'in performans puanını göster")
    assert body["status"] == "SENSITIVE_REQUEST"
    assert called["value"] is False


def test_out_of_scope_question_via_api(app, client):
    _create_user(app, sicil_no="av2_legacy_oos", role="admin")
    _login(client, "av2_legacy_oos")

    body = _ask(client, "yarın hava durumu nasıl olacak?")
    assert body["status"] == "OUT_OF_SCOPE"


# ---------------------------------------------------------------------------
# Phase E/F: conversational intents + identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,expected_marker",
    [
        ("merhaba", "Merhaba"),
        ("teşekkür ederim", "Rica ederim"),
        ("sen nesin?", "BYS360 Kurumsal Asistanı"),
        ("neler yapabilirsin?", "modüller hakkında"),
    ],
)
def test_conversational_intents_via_api(app, client, question, expected_marker):
    _create_user(app, sicil_no="av2_legacy_conv", role="admin")
    _login(client, "av2_legacy_conv")

    body = _ask(client, question)
    assert body["status"] == "CONVERSATIONAL_RESPONSE"
    assert expected_marker in body["answer"]


def test_assistant_identity_answer_has_no_personal_developer_attribution():
    from app.services.assistant_v2.conversational_intents import ASSISTANT_IDENTITY_ANSWER

    lowered = ASSISTANT_IDENTITY_ANSWER.lower()
    for forbidden in ("geliştirici", "yazan", "tarafından yazıl"):
        assert forbidden not in lowered
    assert "BYS360 AI Core" in ASSISTANT_IDENTITY_ANSWER


def test_conversational_response_never_calls_capability_dispatch(app, client, monkeypatch):
    from app.services.assistant_v2 import service as service_module

    called = {"value": False}
    real = service_module.invoke_capability

    def _tracking(*args, **kwargs):
        called["value"] = True
        return real(*args, **kwargs)

    monkeypatch.setattr(service_module, "invoke_capability", _tracking)

    _create_user(app, sicil_no="av2_legacy_conv_nodispatch", role="admin")
    _login(client, "av2_legacy_conv_nodispatch")

    _ask(client, "merhaba")
    assert called["value"] is False


# ---------------------------------------------------------------------------
# Phase D: page context
# ---------------------------------------------------------------------------


def test_resolve_page_context_maps_known_prefix_not_client_invented_name():
    from app.services.assistant_v2.page_context import resolve_page_context

    ctx = resolve_page_context("/performance/tasks")
    assert ctx.module_key == "performance_mgmt"


def test_resolve_page_context_unknown_path_resolves_to_none_not_a_guess():
    from app.services.assistant_v2.page_context import resolve_page_context

    ctx = resolve_page_context("/some/totally/unknown/client-invented-path")
    assert ctx.module_key is None


def test_page_context_never_used_for_authorization(app, client):
    """A restricted user asking a page-context question about an admin-only
    module must NOT get any elevated data -- page context only changes
    WHICH explanatory sentence is shown, never what's authorized."""
    _create_user(app, sicil_no="av2_legacy_pagectx_personel", role="personel")
    _login(client, "av2_legacy_pagectx_personel")

    body = _ask(client, "bu sayfa ne işe yarıyor?", page_path="/settings-center")
    assert body["status"] == "CONVERSATIONAL_RESPONSE"
    assert body["capability_key"] is None  # never dispatched a capability


# ---------------------------------------------------------------------------
# Phase G/H: KPI / Hedef capability
# ---------------------------------------------------------------------------


def test_kpi_capability_uses_real_menu_key_not_invented_module():
    from app.services.assistant_v2.capability_registry import get_capability

    entry = get_capability("performance_mgmt_summarize_kpi_targets")
    assert entry is not None
    assert entry.module_key == "performance_mgmt"
    assert entry.permission_key == "performance_kpi_dashboard"
    assert entry.service_handler == "app.services.ai_agent.dashboard_kpi_bridge.build_dashboard_kpi_summary_for_user"


def test_kpi_capability_denies_role_without_kpi_permission(app):
    from app.services.assistant_v2.capability_dispatcher import invoke_capability
    from app.services.assistant_v2.result_contract import AssistantResultStatus

    personel_id = _create_user(app, sicil_no="av2_legacy_kpi_personel", role="personel")
    with app.app_context():
        from app.models import User

        user = User.query.get(personel_id)
        result = invoke_capability(user, "performance_mgmt_summarize_kpi_targets")
    assert result.status is AssistantResultStatus.ACCESS_DENIED


def test_kpi_capability_allows_role_with_kpi_permission(app):
    from app.services.assistant_v2.capability_dispatcher import invoke_capability
    from app.services.assistant_v2.result_contract import AssistantResultStatus

    admin_id = _create_user(app, sicil_no="av2_legacy_kpi_admin", role="admin")
    with app.app_context():
        from app.models import User

        user = User.query.get(admin_id)
        result = invoke_capability(user, "performance_mgmt_summarize_kpi_targets")
    assert result.status is not AssistantResultStatus.ACCESS_DENIED
