"""BYS360 DEFECT AQ: app/api/mobile/domains/personnel_write_all.py

Behavioral contract for `_can_mobile_create_personnel`, the authorization
gate behind the live `POST /api/mobile/personnel/create` (and its
`/personnel/add` alias) mobile endpoint -- calling the real function
directly against `SimpleNamespace` fake users, no mocking.

The function used to also grant via `"admin" in role`, `"personel_yonetimi"
in role`, and `"personel yönetimi" in label` substring checks -- an
ordinary role value like "birim_admin_full" contains "admin" as a
substring and was incorrectly granted personnel-record creation authority
on the mobile API. All three substring checks added no legitimate coverage
beyond the exact-match `_PERSONNEL_CREATE_ROLES` set they duplicated, so
they were removed entirely rather than converted.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.mobile.domains.personnel_write_all import (
    _PERSONNEL_CREATE_ROLES,
    _can_mobile_create_personnel,
)


def _user(role=None, role_label=None):
    return SimpleNamespace(role=role, role_label=role_label)


@pytest.mark.parametrize("role", sorted(_PERSONNEL_CREATE_ROLES))
def test_allows_every_canonical_role_value(role):
    assert _can_mobile_create_personnel(_user(role=role)) is True


@pytest.mark.parametrize("label", sorted(_PERSONNEL_CREATE_ROLES | {"Admin", "sistem_yoneticisi", "ik"}))
def test_role_label_never_grants_creation(label):
    # B1-F1 decision 3 (HUMAN_POLICY_APPROVED, 2026-10-09): role_label is display text only.
    assert _can_mobile_create_personnel(_user(role_label=label)) is False
    assert _can_mobile_create_personnel(_user(role="personel", role_label=label)) is False


@pytest.mark.parametrize("role", ["ik", "personel_yonetimi", "sistem_yoneticisi", "system_admin"])
def test_b1f1_hr_and_technical_roles_do_not_create_personnel(role):
    # B1-F1 approved policy and decision 2: personnel write is a separate permission.
    assert _can_mobile_create_personnel(_user(role=role)) is False


@pytest.mark.parametrize(
    "role",
    [
        "birim_admin_full",
        "office-admin",
        "personel_yonetimi_talebi",
    ],
)
def test_denies_admin_and_personel_yonetimi_substring_lookalikes(role):
    # BYS360 DEFECT AQ adversarial case: none of these are exact members
    # of _PERSONNEL_CREATE_ROLES, even though each contains a privileged
    # token as a substring.
    assert _can_mobile_create_personnel(_user(role=role)) is False


def test_denies_unknown_role():
    assert _can_mobile_create_personnel(_user(role="personel")) is False


def test_denies_missing_role_and_label():
    assert _can_mobile_create_personnel(_user()) is False
