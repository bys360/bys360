
# BYS360_MOBILE_SERVICE_SCAFFOLD_P1_2_V2_17_7
"""Communication/message service extraction target for mobile routes."""

from __future__ import annotations

from typing import Any


def mobile_b48_communication_v2_create_thread_delegate(*args: Any, **kwargs: Any) -> Any:
    from app.api.mobile.domains import communication_v2_write
    legacy = getattr(communication_v2_write, "_bys360_legacy_mobile_b48_communication_v2_create_thread", None)
    if not callable(legacy):
        raise RuntimeError("BYS360 communication legacy handler not found: _bys360_legacy_mobile_b48_communication_v2_create_thread")
    return legacy(*args, **kwargs)


def mobile_b48_communication_v2_users_delegate(*args: Any, **kwargs: Any) -> Any:
    from app.api.mobile.domains import communication_v2_write
    legacy = getattr(communication_v2_write, "_bys360_legacy_mobile_b48_communication_v2_users", None)
    if not callable(legacy):
        raise RuntimeError("BYS360 communication legacy handler not found: _bys360_legacy_mobile_b48_communication_v2_users")
    return legacy(*args, **kwargs)


def mobile_b48_communication_v2_send_delegate(*args: Any, **kwargs: Any) -> Any:
    from app.api.mobile.domains import communication_v2_write
    legacy = getattr(communication_v2_write, "_bys360_legacy_mobile_b48_communication_v2_send", None)
    if not callable(legacy):
        raise RuntimeError("BYS360 communication legacy handler not found: _bys360_legacy_mobile_b48_communication_v2_send")
    return legacy(*args, **kwargs)


def mobile_b48_communication_v2_thread_detail_delegate(*args: Any, **kwargs: Any) -> Any:
    from app.api.mobile.domains import communication_v2_write
    legacy = getattr(communication_v2_write, "_bys360_legacy_mobile_b48_communication_v2_thread_detail", None)
    if not callable(legacy):
        raise RuntimeError("BYS360 communication legacy handler not found: _bys360_legacy_mobile_b48_communication_v2_thread_detail")
    return legacy(*args, **kwargs)


def _b48_thread_row_delegate(*args: Any, **kwargs: Any) -> Any:
    from app.api.mobile.domains import communication_v2_write
    legacy = getattr(communication_v2_write, "_bys360_legacy__b48_thread_row", None)
    if not callable(legacy):
        raise RuntimeError("BYS360 communication legacy handler not found: _bys360_legacy__b48_thread_row")
    return legacy(*args, **kwargs)


def mobile_b46_communication_create_thread_delegate(*args: Any, **kwargs: Any) -> Any:
    from app.api.mobile.domains import communication_v1_write
    legacy = getattr(communication_v1_write, "_bys360_legacy_mobile_b46_communication_create_thread", None)
    if not callable(legacy):
        raise RuntimeError("BYS360 communication legacy handler not found: _bys360_legacy_mobile_b46_communication_create_thread")
    return legacy(*args, **kwargs)


def mobile_b46_communication_send_message_delegate(*args: Any, **kwargs: Any) -> Any:
    from app.api.mobile.domains import communication_v1_write
    legacy = getattr(communication_v1_write, "_bys360_legacy_mobile_b46_communication_send_message", None)
    if not callable(legacy):
        raise RuntimeError("BYS360 communication legacy handler not found: _bys360_legacy_mobile_b46_communication_send_message")
    return legacy(*args, **kwargs)


def mobile_b46_communication_thread_detail_delegate(*args: Any, **kwargs: Any) -> Any:
    from app.api.mobile.domains import communication_v1_write
    legacy = getattr(communication_v1_write, "_bys360_legacy_mobile_b46_communication_thread_detail", None)
    if not callable(legacy):
        raise RuntimeError("BYS360 communication legacy handler not found: _bys360_legacy_mobile_b46_communication_thread_detail")
    return legacy(*args, **kwargs)


def _b46_thread_row_delegate(*args: Any, **kwargs: Any) -> Any:
    from app.api.mobile.domains import communication_v1_write
    legacy = getattr(communication_v1_write, "_bys360_legacy__b46_thread_row", None)
    if not callable(legacy):
        raise RuntimeError("BYS360 communication legacy handler not found: _bys360_legacy__b46_thread_row")
    return legacy(*args, **kwargs)
