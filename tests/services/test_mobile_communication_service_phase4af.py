from __future__ import annotations

import sys
import types
from importlib import import_module
from typing import Any

import pytest

import app.api.mobile as mobile_package
from app.api.mobile.services import communication_service as svc

DELEGATES = [
    (
        "mobile_b48_communication_v2_create_thread_delegate",
        "_bys360_legacy_mobile_b48_communication_v2_create_thread",
    ),
    (
        "mobile_b48_communication_v2_users_delegate",
        "_bys360_legacy_mobile_b48_communication_v2_users",
    ),
    (
        "mobile_b48_communication_v2_send_delegate",
        "_bys360_legacy_mobile_b48_communication_v2_send",
    ),
    (
        "mobile_b48_communication_v2_thread_detail_delegate",
        "_bys360_legacy_mobile_b48_communication_v2_thread_detail",
    ),
    (
        "_b48_thread_row_delegate",
        "_bys360_legacy__b48_thread_row",
    ),
    (
        "mobile_b46_communication_create_thread_delegate",
        "_bys360_legacy_mobile_b46_communication_create_thread",
    ),
    (
        "mobile_b46_communication_send_message_delegate",
        "_bys360_legacy_mobile_b46_communication_send_message",
    ),
    (
        "mobile_b46_communication_thread_detail_delegate",
        "_bys360_legacy_mobile_b46_communication_thread_detail",
    ),
    (
        "_b46_thread_row_delegate",
        "_bys360_legacy__b46_thread_row",
    ),
]

GET_ONLY_DELEGATES = {
    "mobile_b48_communication_v2_users_delegate",
    "mobile_b48_communication_v2_thread_detail_delegate",
    "mobile_b46_communication_thread_detail_delegate",
}
WRITE_DELEGATES = [pair for pair in DELEGATES if pair[0] not in GET_ONLY_DELEGATES]


def _domain_owner(delegate_name: str) -> types.ModuleType:
    version = "v1" if "b46" in delegate_name else "v2"
    return import_module(f"app.api.mobile.domains.communication_{version}_write")


def _install_fake_mobile_routes(monkeypatch: pytest.MonkeyPatch, **handlers: Any) -> types.ModuleType:
    fake_routes = types.ModuleType("app.api.mobile.routes")

    for name, handler in handlers.items():
        setattr(fake_routes, name, handler)

    monkeypatch.setitem(sys.modules, "app.api.mobile.routes", fake_routes)
    monkeypatch.setattr(mobile_package, "routes", fake_routes, raising=False)
    return fake_routes


@pytest.mark.parametrize(("delegate_name", "legacy_name"), DELEGATES)
def test_mobile_communication_delegate_calls_legacy_handler(
    monkeypatch: pytest.MonkeyPatch,
    delegate_name: str,
    legacy_name: str,
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def legacy_handler(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((args, kwargs))
        return {
            "handler": legacy_name,
            "args": args,
            "kwargs": kwargs,
        }

    if delegate_name in GET_ONLY_DELEGATES:
        _install_fake_mobile_routes(monkeypatch, **{legacy_name: legacy_handler})
    else:
        monkeypatch.setattr(_domain_owner(delegate_name), legacy_name, legacy_handler)

    delegate = getattr(svc, delegate_name)
    result = delegate("alpha", 42, mode="mobile")

    assert result == {
        "handler": legacy_name,
        "args": ("alpha", 42),
        "kwargs": {"mode": "mobile"},
    }
    assert calls == [(("alpha", 42), {"mode": "mobile"})]


@pytest.mark.parametrize(("delegate_name", "legacy_name"), DELEGATES)
def test_mobile_communication_delegate_raises_when_legacy_handler_missing(
    monkeypatch: pytest.MonkeyPatch,
    delegate_name: str,
    legacy_name: str,
) -> None:
    if delegate_name in GET_ONLY_DELEGATES:
        _install_fake_mobile_routes(monkeypatch)
    else:
        monkeypatch.delattr(_domain_owner(delegate_name), legacy_name)

    delegate = getattr(svc, delegate_name)

    with pytest.raises(RuntimeError) as exc_info:
        delegate("alpha", mode="mobile")

    message = str(exc_info.value)
    assert "BYS360 communication legacy handler not found" in message
    assert legacy_name in message


@pytest.mark.parametrize(("delegate_name", "legacy_name"), WRITE_DELEGATES)
def test_write_delegate_reaches_real_domain_implementation_without_facade_export(
    delegate_name: str,
    legacy_name: str,
) -> None:
    from app.api.mobile import routes

    implementation = getattr(_domain_owner(delegate_name), legacy_name)
    assert callable(implementation)
    assert not hasattr(routes, legacy_name)
    user = types.SimpleNamespace(id=1)
    if "thread_row" in delegate_name:
        args = (types.SimpleNamespace(id=1), user)
    elif "send" in delegate_name:
        args = (1, user) if "b46" in delegate_name else (user, 1)
    else:
        args = (user,)

    # No Flask context is supplied: the real handler must be reached and ask
    # for its request/database context, rather than fail at delegate lookup.
    with pytest.raises(RuntimeError, match="Working outside of") as exc_info:
        getattr(svc, delegate_name)(*args)
    frames = []
    traceback = exc_info.value.__traceback__
    while traceback is not None:
        frames.append(traceback.tb_frame.f_code)
        traceback = traceback.tb_next
    assert implementation.__code__ in frames


@pytest.mark.parametrize(("delegate_name", "legacy_name"), WRITE_DELEGATES)
def test_write_delegate_rejects_non_callable_implementation(
    monkeypatch: pytest.MonkeyPatch,
    delegate_name: str,
    legacy_name: str,
) -> None:
    monkeypatch.setattr(_domain_owner(delegate_name), legacy_name, None)
    with pytest.raises(RuntimeError, match=legacy_name):
        getattr(svc, delegate_name)("unused")
