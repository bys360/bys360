"""F-08 / P1: the mobile API honours the forced account security steps of the web login.

An account an admin creates, imports or resets gets ``must_change_password`` and
``must_set_security_question``. The web login sends such a user to the security question setup and
the password change, and ``enforce_first_login_security_flow`` (app/account/routes.py) keeps every
other web page closed until both are done. The mobile API ignored both flags: POST
/api/mobile/auth/login with the initial password returned access and refresh tokens, and every
protected mobile endpoint answered, so the initial (default) password was enough for full mobile
access and the forced steps were never done.

Now (app/api/mobile/shared.py):
- login and refresh issue no tokens while a step is open: 403 with
  ``code = "account_security_required"`` and the open steps; the user completes them on the web;
- ``require_mobile_user``, used by every protected mobile endpoint, refuses a token of such an
  account with the same 403 (tokens issued before an admin set the flags included);
- a wrong password or an inactive account still gets the 401 it got before, so the 403 only
  follows a correct password, as on the web;
- once the steps are done on the web, mobile login and the API work again.

Real create_app() on a temporary SQLite file (R05 fixture), synthetic accounts only.
"""
from __future__ import annotations

import pytest

from tests.security import test_r05_account_change_authority_contract as _r05
from tests.security.test_r05_account_change_authority_contract import PASSWORD, SICIL

env = _r05.env

LOGIN = "/api/mobile/auth/login"
REFRESH = "/api/mobile/auth/refresh"
PUBLIC_MOBILE_ENDPOINTS = {"mobile_api.mobile_login", "mobile_api.mobile_refresh", "mobile_api.mobile_health"}
STEPS = {
    "password": {"must_change_password": True, "must_set_security_question": False},
    "security-question": {"must_change_password": False, "must_set_security_question": True},
    "both": {"must_change_password": True, "must_set_security_question": True},
}
EXPECTED_ACTIONS = {
    "password": ["change_password"],
    "security-question": ["set_security_question"],
    "both": ["set_security_question", "change_password"],
}


def _set_flags(env, who: str, **flags) -> None:
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[who])
        assert user is not None
        for key, value in flags.items():
            setattr(user, key, value)
        db.session.commit()


def _login(client, who: str, password: str = PASSWORD):
    return client.post(LOGIN, json={"username": SICIL[who], "password": password})


def _tokens(env, who: str) -> dict:
    response = _login(env.app.test_client(), who)
    assert response.status_code == 200, response.get_data(as_text=True)[:200]
    return response.get_json()


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assert_security_required(response, step: str) -> None:
    assert response.status_code == 403, response.get_data(as_text=True)[:200]
    body = response.get_json()
    assert body["code"] == "account_security_required"
    assert body["required_actions"] == EXPECTED_ACTIONS[step]
    assert "access_token" not in body and "refresh_token" not in body


def _protected_mobile_rules(app):
    rules = [rule for rule in app.url_map.iter_rules() if rule.endpoint.startswith("mobile_api.")]
    return [rule for rule in rules if rule.endpoint not in PUBLIC_MOBILE_ENDPOINTS]


def _url(rule) -> str:
    return rule.build({name: 1 for name in rule.arguments}, append_unknown=False)[1]


# --------------------------------------------------------------------------- login and refresh


@pytest.mark.parametrize("step", list(STEPS))
def test_login_issues_no_tokens_while_a_forced_step_is_open(env, step):
    _set_flags(env, "plain", **STEPS[step])
    _assert_security_required(_login(env.app.test_client(), "plain"), step)


@pytest.mark.parametrize("step", list(STEPS))
def test_refresh_issues_no_tokens_while_a_forced_step_is_open(env, step):
    tokens = _tokens(env, "plain")  # issued before an admin reset the account
    _set_flags(env, "plain", **STEPS[step])
    response = env.app.test_client().post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
    _assert_security_required(response, step)


def test_wrong_password_and_inactive_account_keep_their_401(env):
    _set_flags(env, "plain", **STEPS["both"])
    client = env.app.test_client()
    assert _login(client, "plain", "wrong-password").status_code == 401
    _set_flags(env, "plain", is_active=False)
    assert _login(client, "plain").status_code == 401


# --------------------------------------------------------------------------- protected endpoints


@pytest.mark.parametrize("step", list(STEPS))
def test_an_earlier_token_opens_no_protected_endpoint_while_a_step_is_open(env, step):
    token = _tokens(env, "plain")["access_token"]
    _set_flags(env, "plain", **STEPS[step])
    client = env.app.test_client()
    _assert_security_required(client.get("/api/mobile/me", headers=_bearer(token)), step)
    _assert_security_required(client.get("/api/mobile/dashboard/summary", headers=_bearer(token)), step)


def test_every_protected_mobile_endpoint_refuses_the_account(env):
    """All mobile endpoints except login, refresh and health: GET and POST alike, before the view runs."""
    from app.extensions import db
    from app.models import SupportTicket

    token = _tokens(env, "admin")["access_token"]
    _set_flags(env, "admin", **STEPS["both"])
    client = env.app.test_client()
    with env.app.app_context():
        tickets_before = db.session.query(SupportTicket).count()
    rules = _protected_mobile_rules(env.app)
    assert len(rules) >= 69
    for rule in rules:
        for method in sorted(set(rule.methods or ()) - {"HEAD", "OPTIONS"}):
            response = client.open(_url(rule), method=method, headers=_bearer(token), json={})
            assert response.status_code == 403, (rule.rule, method, response.status_code)
            assert response.get_json()["code"] == "account_security_required", (rule.rule, method)
    with env.app.app_context():
        assert db.session.query(SupportTicket).count() == tickets_before  # no write went through


def test_every_mobile_endpoint_is_public_by_design_or_requires_the_mobile_user(env):
    """A new mobile endpoint that skips require_mobile_user (and with it this check) fails here."""
    unguarded = []
    for rule in env.app.url_map.iter_rules():
        if not rule.endpoint.startswith("mobile_api.") or rule.endpoint in PUBLIC_MOBILE_ENDPOINTS:
            continue
        view, codes = env.app.view_functions[rule.endpoint], []
        while view is not None:
            codes.append(getattr(getattr(view, "__code__", None), "co_qualname", ""))
            view = getattr(view, "__wrapped__", None)
        if "require_mobile_user.<locals>.wrapper" not in codes:
            unguarded.append(rule.rule)
    assert unguarded == []


def test_health_stays_public(env):
    assert env.app.test_client().get("/api/mobile/health").status_code == 200


# --------------------------------------------------------------------------- recovery and normal use


def test_after_the_steps_are_done_mobile_access_works_again(env):
    _set_flags(env, "plain", **STEPS["both"])
    _assert_security_required(_login(env.app.test_client(), "plain"), "both")
    _set_flags(env, "plain", must_change_password=False, must_set_security_question=False)
    tokens = _tokens(env, "plain")
    client = env.app.test_client()
    assert client.get("/api/mobile/me", headers=_bearer(tokens["access_token"])).status_code == 200
    assert client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]}).status_code == 200


def test_web_completion_flow_stays_reachable(env):
    """The steps are completed on the web: login sends the user there and those pages answer."""
    _set_flags(env, "plain", **STEPS["both"])
    client = env.app.test_client()
    login = client.post("/login", data={"sicil_or_email": SICIL["plain"], "password": PASSWORD})
    assert login.status_code == 302 and "/account/security-setup" in login.headers["Location"]
    assert client.get("/account/security-setup").status_code == 200
    assert client.get("/home").status_code == 302  # other web pages stay closed, as before
    _set_flags(env, "plain", must_set_security_question=False)
    assert client.get("/account/change-password").status_code == 200


def test_accounts_without_open_steps_are_unaffected(env):
    for who in ("plain", "admin", "baskan"):
        tokens = _tokens(env, who)
        assert env.app.test_client().get("/api/mobile/me", headers=_bearer(tokens["access_token"])).status_code == 200
