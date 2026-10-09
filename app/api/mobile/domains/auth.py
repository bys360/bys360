from __future__ import annotations

# BYS360 V1E: emergency runtime recovery for the Phase2Y wildcard-import regression.
# This deliberately restores the shared mobile contract first; explicit imports can be
# reintroduced later only after a per-file F821 gate and smoke test.
from app.api.mobile.shared import (
    User,
    _full_name,
    _issue_refresh_token,
    _issue_token,
    _item,
    _load_refresh_token_user,
    _metric,
    _module_payload,
    mobile_api_bp,
    mobile_login_response,
    mobile_me_response,
    mobile_refresh_response,
    request,
    require_mobile_user,
)


@mobile_api_bp.post("/auth/login")
def mobile_login():
    from app.api.mobile.services.auth_service import delegate_mobile_login
    return delegate_mobile_login(_bys360_legacy_mobile_login)

def _bys360_legacy_mobile_login():
    return mobile_login_response(_issue_token, _issue_refresh_token, _full_name)


@mobile_api_bp.post("/auth/refresh")
def mobile_refresh():
    from app.api.mobile.services.auth_service import delegate_mobile_refresh
    return delegate_mobile_refresh(_bys360_legacy_mobile_refresh)

def _bys360_legacy_mobile_refresh():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    refresh_token = data.get("refresh_token") or data.get("refreshToken")
    if not isinstance(refresh_token, str):
        refresh_token = None  # malformed token: same 401 as a missing one
    return mobile_refresh_response(refresh_token, _load_refresh_token_user, _issue_token, _issue_refresh_token, _full_name)


@mobile_api_bp.get("/me")
@require_mobile_user
def mobile_me(user: User):
    from app.api.mobile.services.auth_service import delegate_mobile_me
    return delegate_mobile_me(_bys360_legacy_mobile_me, user)

def _bys360_legacy_mobile_me(user: User):
    return mobile_me_response(user, _module_payload, _metric, _item, _full_name)

