"""BYS360 PERFORMANCE P0: low-score model publish-gate characterization.

Locks the effective runtime behavior of the four PerformanceLowScoreProcess
publish-gate properties -- is_president_approved, is_president_rejected,
is_second_or_later, is_finalized_for_publish -- exactly as it was at
production SHA 1ea5c5dcf6161104dc8adb04a982cba0eba8e8e6, where each
property was defined in the class body and then re-bound four more times at
module level via ``PerformanceLowScoreProcess.<name> = property(...)``. The
last re-bind block (BYS360_PHASE6_FINAL_POLICY_CONTRACT_V3) was the one
Python actually used at runtime, verified by introspecting each property's
``fget`` after both ``import app.models`` and ``create_app()``.

The ``_frozen_*`` functions below are a verbatim copy of that effective
block. The sweep test compares the model against them over the full input
domain, so any drift from the pre-refactor behavior fails here even if no
named scenario covers it.

Pure transient-instance tests: no app context, no database.
"""
from __future__ import annotations

import itertools
import logging
from datetime import datetime
from typing import Any

import pytest

_MODEL_LOGGER = "app.models.performance_low_score_models"
_DT = datetime(2026, 3, 31, 12, 0, 0)
_POLICY_PROPERTIES = (
    "is_president_approved",
    "is_president_rejected",
    "is_second_or_later",
    "is_finalized_for_publish",
)


# ---------------------------------------------------------------------------
# Frozen pre-refactor oracle: verbatim copy of the effective runtime policy at
# 1ea5c5dc (app/models/performance_low_score_models.py, the
# _bys360_phase6_contract_v3_* block), renamed only.
# ---------------------------------------------------------------------------


def _frozen_is_president_approved(self):
    return bool(getattr(self, "president_approved_at", None) or getattr(self, "president_approved_by_id", None))


def _frozen_is_president_rejected(self):
    return bool(
        getattr(self, "president_rejected_at", None)
        or getattr(self, "president_rejected_by_id", None)
        or getattr(self, "president_rejection_note", None)
    )


def _frozen_is_second_or_later(self):
    try:
        return int(getattr(self, "sequence_no", 1) or 1) >= 2
    except Exception:
        return False


def _frozen_is_finalized_for_publish(self):
    if _frozen_is_president_rejected(self):
        return False
    if not _frozen_is_president_approved(self):
        return False
    if _frozen_is_second_or_later(self):
        return bool(getattr(self, "administrative_process_started_at", None) or getattr(self, "administrative_process_started_by_id", None))
    return bool(getattr(self, "warning_recorded_at", None) or getattr(self, "warning_recorded_by_id", None))


@pytest.fixture(scope="module")
def process_cls() -> Any:
    from app.models import PerformanceLowScoreProcess

    return PerformanceLowScoreProcess


# ---------------------------------------------------------------------------
# Başkan/Üst Onay: approval and rejection detection
# ---------------------------------------------------------------------------


def test_president_approved_at_alone_marks_approved(process_cls) -> None:
    assert process_cls(president_approved_at=_DT).is_president_approved is True
    assert process_cls().is_president_approved is False


def test_president_approved_by_id_alone_marks_approved(process_cls) -> None:
    # Effective runtime behavior: an approver id without a timestamp still
    # counts as approved (the class-body version only read the timestamp,
    # but it was shadowed at import time and never ran).
    assert process_cls(president_approved_by_id=7).is_president_approved is True
    # A falsy id (0) is not an approval.
    assert process_cls(president_approved_by_id=0).is_president_approved is False


def test_president_rejected_at_alone_marks_rejected(process_cls) -> None:
    assert process_cls(president_rejected_at=_DT).is_president_rejected is True
    assert process_cls().is_president_rejected is False


def test_president_rejected_by_id_or_rejection_note_alone_marks_rejected(process_cls) -> None:
    assert process_cls(president_rejected_by_id=7).is_president_rejected is True
    assert process_cls(president_rejection_note="Eksik gerekçe").is_president_rejected is True
    # An empty note is not a rejection.
    assert process_cls(president_rejection_note="").is_president_rejected is False


# ---------------------------------------------------------------------------
# First vs. repeated low score (same calendar year sequence)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sequence_no", [None, 0, 1, "", "0", -1, 1.9])
def test_sequence_no_one_or_unset_is_first_low_score(process_cls, sequence_no) -> None:
    assert process_cls(sequence_no=sequence_no).is_second_or_later is False


@pytest.mark.parametrize("sequence_no", [2, 3, 10, "2", 2.7])
def test_sequence_no_two_or_more_is_repeated_low_score(process_cls, sequence_no) -> None:
    assert process_cls(sequence_no=sequence_no).is_second_or_later is True


def test_unparseable_sequence_no_falls_back_to_first_low_score_and_logs(process_cls, caplog) -> None:
    process = process_cls(sequence_no="bozuk")
    with caplog.at_level(logging.ERROR, logger=_MODEL_LOGGER):
        assert process.is_second_or_later is False
    assert any(record.name == _MODEL_LOGGER and record.levelno == logging.ERROR for record in caplog.records)


# ---------------------------------------------------------------------------
# Publish finalization gate
# ---------------------------------------------------------------------------


def test_not_finalized_without_president_approval(process_cls) -> None:
    first = process_cls(sequence_no=1, warning_recorded_at=_DT, warning_recorded_by_id=7)
    second = process_cls(sequence_no=2, administrative_process_started_at=_DT, administrative_process_started_by_id=7)
    assert first.is_finalized_for_publish is False
    assert second.is_finalized_for_publish is False


@pytest.mark.parametrize(
    "rejection",
    [
        {"president_rejected_at": _DT},
        {"president_rejected_by_id": 7},
        {"president_rejection_note": "İade"},
    ],
)
def test_not_finalized_when_rejected_even_if_every_other_condition_is_met(process_cls, rejection) -> None:
    for sequence_no in (1, 2):
        process = process_cls(
            sequence_no=sequence_no,
            president_approved_at=_DT,
            president_approved_by_id=7,
            warning_recorded_at=_DT,
            administrative_process_started_at=_DT,
            **rejection,
        )
        assert process.is_finalized_for_publish is False


def test_first_low_score_not_finalized_without_warning_record(process_cls) -> None:
    # An administrative process record does not substitute for the first
    # low score's warning record.
    process = process_cls(sequence_no=1, president_approved_at=_DT, administrative_process_started_at=_DT)
    assert process.is_finalized_for_publish is False


def test_second_low_score_not_finalized_without_administrative_process(process_cls) -> None:
    # A warning record does not substitute for the repeated low score's
    # administrative process record.
    process = process_cls(sequence_no=2, president_approved_at=_DT, warning_recorded_at=_DT)
    assert process.is_finalized_for_publish is False


@pytest.mark.parametrize(
    "fields",
    [
        {"sequence_no": 1, "president_approved_at": _DT, "warning_recorded_at": _DT},
        {"sequence_no": 1, "president_approved_by_id": 7, "warning_recorded_by_id": 7},
        {"sequence_no": None, "president_approved_at": _DT, "warning_recorded_at": _DT},
        {"sequence_no": 2, "president_approved_at": _DT, "administrative_process_started_at": _DT},
        {"sequence_no": 3, "president_approved_by_id": 7, "administrative_process_started_by_id": 7},
    ],
)
def test_finalized_when_every_condition_is_met(process_cls, fields) -> None:
    assert process_cls(**fields).is_finalized_for_publish is True


# ---------------------------------------------------------------------------
# Single authoritative definition (post-refactor structural guard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _POLICY_PROPERTIES)
def test_policy_property_has_single_class_body_definition(process_cls, name) -> None:
    # Fails if a module-level ``PerformanceLowScoreProcess.<name> =
    # property(...)`` re-bind (or a double ``@property`` wrap) comes back.
    attr = process_cls.__dict__[name]
    assert isinstance(attr, property)
    assert attr.fget is not None
    assert attr.fget.__qualname__ == f"PerformanceLowScoreProcess.{name}"


# ---------------------------------------------------------------------------
# Same inputs, same outputs: full-domain sweep against the frozen oracle
# ---------------------------------------------------------------------------


def test_model_matches_frozen_pre_refactor_policy_across_input_domain(process_cls) -> None:
    fields = (
        "president_approved_at",
        "president_approved_by_id",
        "president_rejected_at",
        "president_rejected_by_id",
        "president_rejection_note",
        "sequence_no",
        "warning_recorded_at",
        "warning_recorded_by_id",
        "administrative_process_started_at",
        "administrative_process_started_by_id",
    )
    domains: tuple[tuple[Any, ...], ...] = (
        (None, _DT),
        (None, 0, 7),
        (None, _DT),
        (None, 0, 7),
        (None, "", "İade"),
        (None, 0, 1, 2, 3, -1, "2", "0", "", 1.9, 2.7),
        (None, _DT),
        (None, 0, 7),
        (None, _DT),
        (None, 0, 7),
    )
    oracle = (
        _frozen_is_president_approved,
        _frozen_is_president_rejected,
        _frozen_is_second_or_later,
        _frozen_is_finalized_for_publish,
    )

    process = process_cls()
    checked = 0
    mismatches: list[tuple[dict[str, Any], tuple[Any, ...], tuple[bool, ...]]] = []
    for combo in itertools.product(*domains):
        for name, value in zip(fields, combo, strict=True):
            setattr(process, name, value)
        actual = tuple(getattr(process, name) for name in _POLICY_PROPERTIES)
        expected = tuple(bool(fn(process)) for fn in oracle)
        if actual != expected or not all(type(value) is bool for value in actual):
            mismatches.append((dict(zip(fields, combo, strict=True)), actual, expected))
        checked += 1

    assert checked == 42768
    assert mismatches[:10] == []
