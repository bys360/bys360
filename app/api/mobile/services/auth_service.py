# BYS360_MOBILE_SERVICE_SCAFFOLD_P1_2_V2_17_7
"""Auth/Login service extraction target for app/api/mobile/routes.py.

Planned functions from P1.1: mobile_login and auth related helpers.
No active route code is moved in P1.2.
"""
from __future__ import annotations

from collections.abc import Callable

# BYS360_P1_3_AUTH_SERVICE_DELEGATE_START
from typing import Any

from flask import jsonify, request
from sqlalchemy import or_

from app.models import User


def _user_payload(user: User, full_name: Callable[[Any], str]) -> dict[str, Any]:
    return {
        "id": getattr(user, "id", None),
        "full_name": full_name(user),
        "sicil_no": getattr(user, "sicil_no", "") or "",
        "role": getattr(user, "role_label", None) or getattr(user, "role", "") or "",
        "unit": getattr(user, "birim", None) or getattr(user, "ust_birim", "") or "",
    }


def mobile_login_response(
    issue_token: Callable[[User], str],
    issue_refresh_token: Callable[[User], str],
    full_name: Callable[[Any], str],
):
    """Mobil giriş yanıtını üretir; route URL/endpoint değişmeden servis delegasyonu sağlar."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    # Non-string values are treated as missing (400), not as a server error.
    username = data.get("username")
    username = username.strip() if isinstance(username, str) else ""
    password = data.get("password")
    password = password if isinstance(password, str) else ""
    if not username or not password:
        return jsonify({"message": "Kullanıcı adı/sicil ve şifre zorunludur."}), 400

    user = User.query.filter(or_(User.sicil_no == username, User.email == username)).first()
    if not user or not user.check_password(password) or not getattr(user, "is_active", True):
        return jsonify({"message": "Kullanıcı adı/sicil veya şifre hatalı."}), 401

    return jsonify({
        "access_token": issue_token(user),
        "refresh_token": issue_refresh_token(user),
        "token_type": "Bearer",
        "user": _user_payload(user, full_name),
    })


def mobile_refresh_response(
    refresh_token: str | None,
    load_refresh_token_user: Callable[[str | None], User | None],
    issue_token: Callable[[User], str],
    issue_refresh_token: Callable[[User], str],
    full_name: Callable[[Any], str],
):
    """Mobil token yenileme yanıtını üretir."""
    user = load_refresh_token_user(refresh_token)
    if not user:
        return jsonify({"message": "Mobil oturum yenilenemedi. Lütfen tekrar giriş yapın."}), 401
    return jsonify({
        "access_token": issue_token(user),
        "refresh_token": issue_refresh_token(user),
        "token_type": "Bearer",
        "user": _user_payload(user, full_name),
    })


def mobile_me_response(
    user: User,
    module_payload: Callable[..., Any],
    metric: Callable[..., dict[str, Any]],
    item: Callable[..., dict[str, Any]],
    full_name: Callable[[Any], str],
):
    """Mevcut /me formatını koruyarak profil özetini servis katmanından üretir."""
    return module_payload(
        metrics=[
            metric("Oturum", "Aktif", "Gerçek mobil API token", "red", "verified_user"),
            metric("Rol", getattr(user, "role_label", None) or getattr(user, "role", "-"), "Yetki kontrollü erişim", "red", "badge"),
            metric("Sicil", getattr(user, "sicil_no", "-"), "Kurum içi kullanıcı kimliği", "red", "person"),
        ],
        items=[
            item(
                getattr(user, "id", ""),
                full_name(user),
                getattr(user, "birim", "") or getattr(user, "ust_birim", ""),
                "Aktif",
                getattr(user, "role_label", None) or getattr(user, "role", ""),
                getattr(user, "sicil_no", ""),
                100,
            )
        ],
    )
# BYS360_P1_3_AUTH_SERVICE_DELEGATE_END
def _run_legacy_route(legacy_fn, *args, **kwargs):
    """Run an extracted legacy route implementation without changing endpoint behavior."""
    return legacy_fn(*args, **kwargs)

def delegate_mobile_login(legacy_fn, *args, **kwargs):
    """Delegate wrapper for mobile_login; keeps route endpoint and URL stable."""
    return _run_legacy_route(legacy_fn, *args, **kwargs)

def delegate_mobile_refresh(legacy_fn, *args, **kwargs):
    """Delegate wrapper for mobile_refresh; keeps route endpoint and URL stable."""
    return _run_legacy_route(legacy_fn, *args, **kwargs)

def delegate_mobile_me(legacy_fn, *args, **kwargs):
    """Delegate wrapper for mobile_me; keeps route endpoint and URL stable."""
    return _run_legacy_route(legacy_fn, *args, **kwargs)

