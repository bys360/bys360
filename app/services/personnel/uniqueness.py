
"""Personel tekillik ve çakışma kontrol yardımcıları.

Faz 5 kapsamı:
- Sicil no / e-posta tekillik kontrollerini servis katmanında toplar.
- Amir seçim çakışmalarını tek yerde doğrular.
- Şifre değişikliği çakışma kontrollerini route davranışını değiştirmeden köprüler.
- Veritabanına yazmaz; commit/rollback çalıştırmaz.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PersonnelConflictValidationResult:
    ok: bool
    errors: tuple[str, ...]
    conflict_fields: tuple[str, ...] = ()
    route_contract: str = "preserved"
    db_commit: bool = False
    db_rollback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_email(value: Any) -> str:
    return _clean_text(value).lower()


def _clean_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _query_first_by_field(user_model: Any, field_name: str, value: str, *, exclude_user_id: int | None = None) -> Any:
    """Return first conflicting user for a field without mutating DB state.

    sicil_no and email are compared like the login lookup (app/services/account_lookup.py):
    trimmed and case-insensitive, so a case variant of an existing identifier is a conflict
    instead of a second, unreachable account.
    """
    if not value or not hasattr(user_model, field_name):
        return None

    from app.services.account_lookup import email_matches, sicil_matches

    query = user_model.query
    field = getattr(user_model, field_name)
    if field_name == "email":
        condition = email_matches(field, value)
    elif field_name == "sicil_no":
        condition = sicil_matches(field, value)
    else:
        condition = field == value
    if exclude_user_id:
        query = query.filter(condition, user_model.id != exclude_user_id)
    else:
        query = query.filter(condition)
    return query.first()


def validate_personnel_identity_uniqueness(
    *,
    user_model: Any,
    email: str,
    sicil_no: str,
    exclude_user_id: int | None = None,
) -> PersonnelConflictValidationResult:
    """Validate e-posta and sicil no uniqueness with optional current-user exclusion."""
    errors: list[str] = []
    fields: list[str] = []

    clean_email = _clean_email(email)
    clean_sicil = _clean_text(sicil_no)

    if _query_first_by_field(user_model, "email", clean_email, exclude_user_id=exclude_user_id):
        errors.append("email_exists")
        fields.append("email")

    if _query_first_by_field(user_model, "sicil_no", clean_sicil, exclude_user_id=exclude_user_id):
        errors.append("sicil_no_exists")
        fields.append("sicil_no")

    return PersonnelConflictValidationResult(ok=not errors, errors=tuple(errors), conflict_fields=tuple(fields))


def validate_personnel_manager_id_conflicts(
    *,
    current_user_id: int | None,
    manager_ids: Iterable[int | None],
) -> PersonnelConflictValidationResult:
    """Validate manager id selections used by /personnel edit form."""
    clean_ids = [value for value in (_clean_int(item) for item in manager_ids) if value]
    errors: list[str] = []
    fields: list[str] = []

    if current_user_id and int(current_user_id) in clean_ids:
        errors.append("self_manager_not_allowed")
        fields.append("manager_ids")
    if len(clean_ids) != len(set(clean_ids)):
        errors.append("duplicate_manager_not_allowed")
        fields.append("manager_ids")

    return PersonnelConflictValidationResult(ok=not errors, errors=tuple(errors), conflict_fields=tuple(fields))


def validate_admin_manager_sicil_conflicts(
    *,
    self_sicil_no: str,
    manager_sicils: Iterable[str | None],
) -> PersonnelConflictValidationResult:
    """Validate legacy admin user form manager sicil selections."""
    own_sicil = _clean_text(self_sicil_no)
    clean_values = [_clean_text(item) for item in manager_sicils if _clean_text(item)]
    errors: list[str] = []
    fields: list[str] = []

    if own_sicil and own_sicil in clean_values:
        errors.append("self_manager_not_allowed")
        fields.append("manager_sicils")
    if len(clean_values) != len(set(clean_values)):
        errors.append("duplicate_manager_not_allowed")
        fields.append("manager_sicils")

    return PersonnelConflictValidationResult(ok=not errors, errors=tuple(errors), conflict_fields=tuple(fields))


def validate_personnel_password_change_conflicts(
    *,
    new_password: str,
    new_password_repeat: str,
) -> PersonnelConflictValidationResult:
    """Validate optional admin password reset fields without applying a password."""
    password = _clean_text(new_password)
    repeat = _clean_text(new_password_repeat)
    if not password and not repeat:
        return PersonnelConflictValidationResult(ok=True, errors=())

    errors: list[str] = []
    fields: list[str] = []
    if len(password) < 8:
        errors.append("password_min_length")
        fields.append("new_password")
    if password != repeat:
        errors.append("password_repeat_mismatch")
        fields.append("new_password_repeat")

    return PersonnelConflictValidationResult(ok=not errors, errors=tuple(errors), conflict_fields=tuple(fields))


def build_personnel_uniqueness_phase5_summary() -> dict[str, Any]:
    return {
        "phase": "personnel_service_faz5",
        "scope": "identity_uniqueness_and_conflict_controls",
        "route_contract": "preserved",
        "db_commit": False,
        "db_rollback": False,
        "checks": [
            "email_uniqueness",
            "sicil_no_uniqueness",
            "manager_self_selection",
            "manager_duplicate_selection",
            "optional_password_reset_conflicts",
        ],
    }
