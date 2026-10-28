from __future__ import annotations

from app.api.mobile.services import assistant_service as svc


# BYS360 Assistant V2 MOBILE BACKEND CUTOVER (mandate Phase I): the two unit
# tests that used to assert delegate_mobile_b49_assistant_v2_ask forwarded
# its raw args/kwargs verbatim to the independent legacy rule-based handler
# have been REPLACED below -- that forwarding behavior was the old contract
# being cut over away from, not a regression to preserve. See
# test_assistant_v2_mobile_cutover_contract_v1.py for the full behavioral
# regression suite (auth, schema, denial, procedural steps).
def test_delegate_mobile_b49_assistant_v2_ask_calls_assistant_v2_service(app, monkeypatch):
    from app.services.assistant_v2 import service as service_module

    called = {"value": False}
    real_ask = service_module.AssistantV2Service.ask

    def _tracking_ask(self, *args, **kwargs):
        called["value"] = True
        return real_ask(self, *args, **kwargs)

    monkeypatch.setattr(service_module.AssistantV2Service, "ask", _tracking_ask)

    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User.query.filter_by(sicil_no="phase4al-delegate-unit-test").first()
        if user is None:
            user = User(sicil_no="phase4al-delegate-unit-test", email="phase4al-delegate-unit-test@example.invalid", ad="T", soyad="U", role="admin")
            user.set_password("Assist_v2_Test_Pw_1!")
            db.session.add(user)
            db.session.commit()
        with app.test_request_context("/api/mobile/assistant/v2/ask", json={"question": "merhaba"}):
            svc.delegate_mobile_b49_assistant_v2_ask(user)

    assert called["value"] is True


def test_delegate_mobile_b49_assistant_v2_ask_response_has_mobile_schema(app):
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = User.query.filter_by(sicil_no="phase4al-delegate-schema-test").first()
        if user is None:
            user = User(sicil_no="phase4al-delegate-schema-test", email="phase4al-delegate-schema-test@example.invalid", ad="T", soyad="U", role="admin")
            user.set_password("Assist_v2_Test_Pw_1!")
            db.session.add(user)
            db.session.commit()
        with app.test_request_context("/api/mobile/assistant/v2/ask", json={"question": "merhaba"}):
            response = svc.delegate_mobile_b49_assistant_v2_ask(user)
            body = response.get_json()

    for key in ("answer", "module", "route_hint", "required_roles", "steps", "warnings", "control_items", "suggested_questions", "intent", "source", "metrics", "user_label"):
        assert key in body


def test_assistant_v2_ask_route_end_to_end(app, client) -> None:
    """Real /assistant/v2/ask endpoint must not 500, and must now answer via
    AssistantV2Service (the mobile backend cutover), not the independent
    rule-based engine."""
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with app.app_context():
        user = db.session.query(User).filter_by(sicil_no="phase4al-assistant-test").one_or_none()
        if user is None:
            user = User(
                sicil_no="phase4al-assistant-test",
                email="phase4al-assistant-test@example.invalid",
                password_hash="x",
                ad="Test",
                soyad="User",
                role="admin",
            )
            db.session.add(user)
        # An account that finished the forced first-login steps (the model defaults leave both
        # open, and the mobile API refuses such accounts: F-08).
        user.must_change_password = False
        user.must_set_security_question = False
        db.session.commit()
        token = _issue_token(user)

    response = client.post(
        "/api/mobile/assistant/v2/ask",
        json={"question": "performans dönemi nasıl oluşturulur?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source"] == "bys360_mobile_assistant_v2_8_49"
    assert "1. " in payload["answer"]
    assert payload["intent"] == "PROCEDURAL_GUIDE"
