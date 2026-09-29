"""BYS360 Assistant V2 -- HTML/XSS safety contract (mandate Phase M).

The V2 API is JSON-only (never server-rendered HTML), so the actual escaping
boundary is client-side: `app/static/js/bys360_assistant_module.js` and
`app/static/js/bys360_assistant_module_memory_v30.js` render every answer
via `textContent`/`escapeText()`-before-`innerHTML`, never raw `innerHTML`
of untrusted text (verified directly in a live browser session for this
mandate: an `<img onerror>` payload submitted through the real chat form
never executed and never appears unescaped in the DOM). This file proves
the SERVER side of that contract: an unsafe string embedded in real content
from portal/support/survey/knowledge-bank/personnel/procedural-guide
sources is never treated specially (no HTML entity pre-decoding, no `|safe`-
equivalent transformation) -- it arrives at the JSON boundary as inert text,
exactly as stored, so the already-proven client-side escaping is the only
thing standing between it and the DOM (matching a defense-in-depth review,
not because the server itself renders HTML).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.ci_safe

_PASSWORD = "Assist_v2_Test_Pw_1!"
_XSS_PAYLOAD = "<script>alert(1)</script>"


def _create_user(app, *, sicil_no, role, password=_PASSWORD):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        existing = User.query.filter_by(sicil_no=sicil_no).first()
        if existing is not None:
            return existing.id
        user = User(
            sicil_no=sicil_no, email=f"{sicil_no}@ktb.gov.tr", ad="Xss", soyad="Test",
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


def test_no_ai_agent_or_settings_center_template_uses_safe_filter():
    """Jinja auto-escaping must stay on for every assistant-facing template
    -- a `|safe` filter would bypass it for whatever content follows."""
    import pathlib

    templates = list(pathlib.Path("app/templates/ai_agent").glob("*.html")) + list(
        pathlib.Path("app/templates/settings_center").glob("*.html")
    )
    assert templates, "expected to find assistant/settings-center templates"
    for path in templates:
        content = path.read_text(encoding="utf-8")
        assert "|safe" not in content, f"{path} uses the |safe filter -- review required"


def test_user_question_containing_script_tag_never_echoed_in_answer(app, client):
    _create_user(app, sicil_no="av2_xss_question_admin", role="admin")
    _login(client, "av2_xss_question_admin")

    response = client.post("/ai-agent/api/ask", json={"question": f"{_XSS_PAYLOAD} personel nasıl eklenir"})
    assert response.status_code == 200
    body = response.get_json()
    assert _XSS_PAYLOAD not in body["answer"]
    assert _XSS_PAYLOAD not in str(body)


def test_procedural_guide_content_survives_round_trip_without_html_transformation(app, client):
    """The guide registry's own steps/warnings text (which legitimately
    contains apostrophes and Turkish punctuation) must reach the JSON
    response byte-for-byte -- proving no server-side HTML-encoding pass
    runs over it (which would double-escape when the client also escapes)."""
    from app.services.assistant_v2.procedural_guides import get_guide

    _create_user(app, sicil_no="av2_xss_guide_admin", role="admin")
    _login(client, "av2_xss_guide_admin")

    entry = get_guide("personnel_hr_guide_add_employee")
    assert entry is not None
    response = client.post("/ai-agent/api/ask", json={"question": "personel nasıl eklenir"})
    body = response.get_json()
    assert "&amp;" not in body["answer"]
    assert "&lt;" not in body["answer"]
    assert entry.steps[0] in body["answer"]


def test_knowledge_bank_entry_with_script_like_title_is_never_html_escaped_server_side(app, client):
    """A knowledge-bank entry TITLE containing an unsafe-looking string
    (titles, not full answer bodies, are what the list-style composer
    surfaces -- see test_knowledge_bank_question_routes_through_api in the
    legacy-migration contract for the single-match full-answer case) must
    reach the API exactly as stored -- proving the server performs no
    partial/incorrect escaping pass that could combine badly with the
    client's own escaping."""
    import uuid

    from app.extensions import db
    from app.services.ai_agent.knowledge import create_knowledge_entry, provision_knowledge_table

    unique_kw = f"av2 xss soru kalibi {uuid.uuid4().hex[:8]}"
    with app.app_context():
        provision_knowledge_table()
        create_knowledge_entry(
            title=f"AV2 XSS {_XSS_PAYLOAD} Title",
            question_patterns=unique_kw,
            answer="Güvenli cevap metni.",
        )
        db.session.commit()

    _create_user(app, sicil_no="av2_xss_kb_admin", role="admin")
    _login(client, "av2_xss_kb_admin")

    response = client.post("/ai-agent/api/ask", json={"question": unique_kw})
    body = response.get_json()
    assert _XSS_PAYLOAD in body["answer"]  # present verbatim in the JSON payload...
    assert "&lt;script&gt;" not in body["answer"]  # ...never pre-HTML-escaped by the server


def test_source_chip_and_module_label_never_contain_raw_html_markup(app, client):
    _create_user(app, sicil_no="av2_xss_chips_admin", role="admin")
    _login(client, "av2_xss_chips_admin")

    response = client.post("/ai-agent/api/ask", json={"question": "kpi hedef nasıl kullanılır"})
    body = response.get_json()
    assert body["module"] == "Performans Yönetimi"
    for source in body["sources"]:
        assert "<" not in source["label"]
        assert ">" not in source["label"]


def test_support_ticket_title_with_xss_payload_reaches_json_unescaped_by_server(app):
    """A support-ticket title (rendered via response_composer's generic
    list renderer, exactly the same code path portal/personnel/survey
    labels flow through) must never be pre-HTML-escaped server side.
    Dispatched directly (not via the NLU router) to decouple this security
    property from routing-quality flakiness, matching this test suite's
    established convention for security-focused tests."""
    from app.extensions import db
    from app.models.support_models import SupportTicket
    from app.services.assistant_v2.capability_dispatcher import invoke_capability
    from app.services.assistant_v2.response_composer import compose_response

    admin_id = _create_user(app, sicil_no="av2_xss_ticket_admin", role="admin")
    with app.app_context():
        if SupportTicket.query.filter_by(ticket_no="AV2-XSS-TICKET-1").first() is None:
            db.session.add(SupportTicket(
                ticket_no="AV2-XSS-TICKET-1", title=f"AV2 XSS {_XSS_PAYLOAD} Ticket", description="t",
                ticket_type="general", module_name="assistant_v2_xss_test", created_by_user_id=admin_id,
                status="open", priority="normal",
            ))
            db.session.commit()

        from app.models import User

        admin = User.query.get(admin_id)
        result = invoke_capability(admin, "support_help_list_my_tickets")
        composed = compose_response(result)

    assert result.status.value == "DATA_FOUND"
    assert _XSS_PAYLOAD in composed.answer_text
    assert "&lt;script&gt;" not in composed.answer_text


def test_personnel_label_with_xss_payload_reaches_json_unescaped_by_server():
    """A personnel display name flowing through the generic list renderer
    must never be pre-HTML-escaped server side. Exercised directly against
    the composer with synthetic personnel-row-shaped data (the same shape
    `personnel_hr_list_personnel` returns) -- deterministic, independent of
    how many personnel rows a shared test database has accumulated (a real
    DB row's ordering position is not a security property worth coupling
    this test to)."""
    from app.services.assistant_v2.response_composer import compose_response
    from app.services.assistant_v2.result_contract import (
        AssistantCapabilityResult,
        AssistantResultStatus,
    )

    result = AssistantCapabilityResult(
        status=AssistantResultStatus.DATA_FOUND,
        message="İstenen bilgi bulundu.",
        capability_key="personnel_hr_list_personnel",
        module_key="personnel_hr",
        data=[{"full_name": f"Xss{_XSS_PAYLOAD} Target", "sicil_no": "av2_xss_personnel_target"}],
        source_label="Personel Listesi",
    )
    composed = compose_response(result)
    assert _XSS_PAYLOAD in composed.answer_text
    assert "&lt;script&gt;" not in composed.answer_text
