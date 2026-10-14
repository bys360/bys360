"""One login-identifier lookup for the web login, /forgot-password and the mobile login.

The three entry points matched the identifier differently (web: sicil exact, e-mail against the
lower-cased input; mobile: both exact). An identifier typed in another case, a stored e-mail with
capitals, or an invisible character copied with the identifier ended in "Kullanıcı bulunamadı"
although the account existed.

Rule: an identifier with "@" is an e-mail and is compared with e-mails only; any other identifier
is a sicil and is compared with sicils only, so an account whose sicil looks like someone's e-mail
never captures that person's login. An exact match wins; otherwise the value is compared
case-insensitively, trimmed and without zero-width characters, but only for an ASCII identifier
(no Unicode case-fold look-alikes such as the long s, the dotless i or the Kelvin sign). If more
than one account matches that way, nobody is returned, so an ambiguous identifier never logs into
the wrong account. The password and every other check stay with the caller.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func

logger = logging.getLogger(__name__)

_INVISIBLE = {ord(char): None for char in "​‌‍⁠﻿"}


def normalize_login_identifier(value: Any) -> str:
    """Strip whitespace and zero-width characters; keep the case (exact matches first)."""
    return str(value or "").translate(_INVISIBLE).strip()


def normalized_sicil(value: Any) -> str:
    return normalize_login_identifier(value).upper()


def normalized_email(value: Any) -> str:
    return normalize_login_identifier(value).lower()


def sicil_matches(column: Any, value: Any) -> Any:
    """SQL: case-insensitive, trimmed sicil comparison."""
    return func.upper(func.trim(column)) == normalized_sicil(value)


def email_matches(column: Any, value: Any) -> Any:
    """SQL: case-insensitive, trimmed e-mail comparison."""
    return func.lower(func.trim(column)) == normalized_email(value)


def find_user_by_login_identifier(value: Any) -> Any | None:
    """The account a sicil or e-mail identifies, or None (also when ambiguous)."""
    from app.models import User

    identifier = normalize_login_identifier(value)
    if not identifier:
        return None
    if "@" in identifier:
        exact = User.query.filter(User.email == identifier).first()
        if exact is None and identifier.isascii():
            exact = User.query.filter(User.email == identifier.lower()).first()
        folded = email_matches(User.email, identifier)
    else:
        exact = User.query.filter(User.sicil_no == identifier).first()
        folded = sicil_matches(User.sicil_no, identifier)
    if exact is not None:
        return exact
    if not identifier.isascii():
        return None
    candidates = User.query.filter(folded).limit(2).all()
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        logger.warning("BYS360 login identifier matches more than one account case-insensitively; refusing.")
    return None
