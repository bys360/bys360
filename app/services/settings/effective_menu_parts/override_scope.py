"""Kişi bazlı menü kayıtlarını geçici olarak yok sayan bağlam (K2, 18 Ekim 2026).

Erişim anındaki yetki tavanı, bir anahtarın kişi kaydı olmadan da görünüp görünmeyeceğini bilmek için
menü haritasını kişi kayıtları okunmadan bir kez daha üretir. Bu modül bilerek bağımlılıksızdır: menü
katmanları döngüsel içe aktarma olmadan okuyabilsin.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_SUPPRESSED: ContextVar[bool] = ContextVar("bys360_user_menu_overrides_suppressed", default=False)


def user_overrides_suppressed() -> bool:
    return _SUPPRESSED.get()


@contextmanager
def suppress_user_overrides() -> Iterator[None]:
    token = _SUPPRESSED.set(True)
    try:
        yield
    finally:
        _SUPPRESSED.reset(token)
