"""BYS360 Assistant V2 -- web cutover contract (mandate Phase F/P): the
normal, production-facing `/ai-agent/api/ask` route now answers via
`AssistantV2Service`, not the legacy `build_ai_agent_reply` chain. The
legacy chain itself is left in place (not deleted) but must no longer be
invoked by this route.
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
            sicil_no=sicil_no, email=f"{sicil_no}@ktb.gov.tr", ad="Cutover", soyad="Test",
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


def test_live_ask_route_calls_assistant_v2_service_not_legacy_chain(app, client, monkeypatch):
    from app.ai_agent import routes as ai_agent_routes
    from app.services.assistant_v2 import service as service_module

    legacy_called = {"value": False}
    v2_called = {"value": False}

    monkeypatch.setattr(ai_agent_routes, "build_ai_agent_reply", lambda *a, **k: legacy_called.update(value=True), raising=False)
    real_ask = service_module.AssistantV2Service.ask

    def _tracking_ask(self, *args, **kwargs):
        v2_called["value"] = True
        return real_ask(self, *args, **kwargs)

    monkeypatch.setattr(service_module.AssistantV2Service, "ask", _tracking_ask)

    _create_user(app, sicil_no="av2_cutover_admin", role="admin")
    _login(client, "av2_cutover_admin")

    response = client.post("/ai-agent/api/ask", json={"question": "merhaba"})
    assert response.status_code == 200
    assert v2_called["value"] is True
    assert legacy_called["value"] is False


def test_live_ask_route_response_shape_matches_legacy_widget_contract(app, client):
    _create_user(app, sicil_no="av2_cutover_shape", role="admin")
    _login(client, "av2_cutover_shape")

    response = client.post("/ai-agent/api/ask", json={"question": "merhaba"})
    assert response.status_code == 200
    body = response.get_json()
    assert "answer" in body
    assert "actions" in body
    assert isinstance(body["actions"], list)
    # The legacy-shaped response deliberately does NOT leak the V2-internal
    # status enum, capability_key, or conversation_id -- the widget never
    # reads those fields and this keeps the legacy contract minimal/stable.
    assert "status" not in body
    assert "capability_key" not in body


def test_live_ask_route_response_includes_ui_enrichment_fields(app, client):
    """Phase L UI enrichment: sources/module/suggested_questions are
    additive fields the widget/panel now render as provenance chips, a
    module badge, and clickable suggestion chips -- never required, but
    must be present in the shape the front-end JS expects."""
    _create_user(app, sicil_no="av2_cutover_uifields", role="admin")
    _login(client, "av2_cutover_uifields")

    response = client.post("/ai-agent/api/ask", json={"question": "personel nasıl eklenir"})
    body = response.get_json()
    assert "sources" in body
    assert "module" in body
    assert "suggested_questions" in body
    assert isinstance(body["sources"], list)
    assert isinstance(body["suggested_questions"], list)
    assert body["module"] == "Personel / İK"


def test_live_ask_route_procedural_guide_answer_reaches_widget(app, client):
    _create_user(app, sicil_no="av2_cutover_guide", role="admin")
    _login(client, "av2_cutover_guide")

    response = client.post("/ai-agent/api/ask", json={"question": "destek talebi nasıl açılır"})
    assert response.status_code == 200
    body = response.get_json()
    assert "1. " in body["answer"]


def test_live_ask_route_access_denied_still_denies(app, client):
    """Dynamically derives a capability that's actually denied to 'personel'
    from the REAL live authorization system (never a hardcoded assumption
    about a specific role/capability pairing -- see
    test_assistant_v2_capability_success_denial_matrix_v1.py for why)."""
    from app.route_support import can_access_menu
    from app.services.assistant_v2.capability_registry import ASSISTANT_CAPABILITY_REGISTRY

    personel_id = _create_user(app, sicil_no="av2_cutover_denied", role="personel")
    with app.test_request_context():
        from app.models import User

        personel = User.query.get(personel_id)
        denied_entry = next(
            (
                e for e in ASSISTANT_CAPABILITY_REGISTRY
                if e.permission_key and not e.is_self_describing and not can_access_menu(personel, e.permission_key)
            ),
            None,
        )
    assert denied_entry is not None, "expected at least one capability denied to 'personel' in this registry"

    _login(client, "av2_cutover_denied")
    response = client.post("/ai-agent/api/ask", json={"question": denied_entry.intent_tags[0]})
    assert response.status_code == 200
    body = response.get_json()
    # A denied capability must never leak actual data through the legacy-
    # shaped route either -- either a clean denial phrase, or (if routing
    # confidence didn't land on this exact capability) a clarification, but
    # never the capability's own source-attribution/data content.
    assert "erişim yetkisi" in body["answer"].lower() or "tam olarak anlayamadım" in body["answer"].lower()


def test_live_ask_route_knowledge_bank_still_works(app, client):
    from app.extensions import db
    from app.services.ai_agent.knowledge import create_knowledge_entry, provision_knowledge_table

    with app.app_context():
        provision_knowledge_table()
        create_knowledge_entry(
            title="AV2 Cutover Test Entry",
            question_patterns="av2 cutover test benzersiz soru kalibi",
            answer="Bu öğretilmiş bir bilgi bankası cevabıdır.",
        )
        db.session.commit()

    _create_user(app, sicil_no="av2_cutover_kb", role="admin")
    _login(client, "av2_cutover_kb")

    response = client.post("/ai-agent/api/ask", json={"question": "av2 cutover test benzersiz soru kalibi"})
    assert response.status_code == 200
    assert "Bilgi Bankası" in response.get_json()["answer"]


def test_live_ask_route_kpi_capability_still_works(app, client):
    _create_user(app, sicil_no="av2_cutover_kpi", role="admin")
    _login(client, "av2_cutover_kpi")

    response = client.post("/ai-agent/api/ask", json={"question": "kpi hedef durumu"})
    assert response.status_code == 200
    assert response.get_json()["answer"]


def test_legacy_build_ai_agent_reply_is_no_longer_imported_by_ai_agent_routes():
    """Phase G groundwork: confirms this specific module no longer even
    imports the legacy reply builder (mechanical, not a full app-wide
    claim -- Phase G's own report covers the rest of the chain)."""
    from app.ai_agent import routes as ai_agent_routes

    assert not hasattr(ai_agent_routes, "build_ai_agent_reply")
