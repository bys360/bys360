"""One login-identifier lookup for the web login, /forgot-password and the mobile login.

The three entry points matched the identifier differently (web: sicil exact, e-mail against the
lower-cased input; mobile: both exact). An identifier typed in another case, a stored e-mail with
capitals, or an invisible character copied with the identifier ended in "Kullanıcı bulunamadı"
although the account existed.

Rule: an exact match keeps winning (sicil first, then e-mail); otherwise the sicil and the e-mail
are compared case-insensitively, trimmed and without zero-width characters. If more than one
account matches that way, nobody is returned, so an ambiguous identifier never logs into the
wrong account. The password and every other check stay with the caller.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, or_

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
    exact = User.query.filter(User.sicil_no == identifier).first()
    if exact is None:
        exact = User.query.filter(User.email == identifier.lower()).first()
    if exact is not None:
        return exact
    candidates = (
        User.query.filter(or_(sicil_matches(User.sicil_no, identifier), email_matches(User.email, identifier)))
        .limit(2)
        .all()
    )
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        logger.warning("BYS360 login identifier matches more than one account case-insensitively; refusing.")
    return None
