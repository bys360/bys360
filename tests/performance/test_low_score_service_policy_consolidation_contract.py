"""BYS360 PERFORMANCE P0.1: low-score service policy characterization.

Locks the behavior of the low_score_process_service decisions that re-derive
the Başkan/Üst Onay publish policy from raw columns, as of commit
178e55bd5897bc11bd811dd2c93a85519205a932 (after P0 canonicalized the
PerformanceLowScoreProcess properties):

- get_low_score_publish_block_reason (process path)
- auto_record_first_low_score_warning / auto_start_second_low_score_process
  (the approval gate that decides whether the next step fires)
- _sync_current_stage (status / current_stage_key / current_owner_label)

The ``_frozen_*`` functions are verbatim copies of that code. Each sweep runs
the live service against them over the full field domain, for both real
(transient) PerformanceLowScoreProcess instances and the duck-typed
process-like objects the service also accepts (see
tests/services/test_low_score_process_service_phase4t.py).

Pure tests: no app context and no database. The DB-backed approve/reject
flows stay covered by
tests/behavior/test_low_score_process_service_workflow_contract.py.
"""
from __future__ import annotations

import itertools
import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

_DT = datetime(2026, 3, 31, 12, 0, 0)
_LOW_SCORE = 50.0
_SEQUENCE_DOMAIN: tuple[Any, ...] = (None, 0, 1, 2, 3, -1, "2", "0", "", 1.9, 2.7)
_POLICY_FIELDS = (
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
_POLICY_DOMAINS: tuple[tuple[Any, ...], ...] = (
    (None, _DT),
    (None, 0, 7),
    (None, _DT),
    (None, 0, 7),
    (None, "", "İade"),
    _SEQUENCE_DOMAIN,
    (None, _DT),
    (None, 0, 7),
    (None, _DT),
    (None, 0, 7),
)
_POLICY_DOMAIN_SIZE = 42768


# ---------------------------------------------------------------------------
# Frozen pre-refactor oracles: verbatim copies of
# app/services/performance/low_score_process_service.py at 178e55bd.
# ---------------------------------------------------------------------------


def _frozen_safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _frozen_publish_block_reason(target):
    final_score = _frozen_safe_float(getattr(target, "final_total_100", 0), 0.0)
    if final_score <= 0 or final_score >= 70.0:
        return None
    if getattr(target, "president_rejected_at", None) or getattr(target, "president_rejected_by_id", None) or getattr(target, "president_rejection_note", None):
        return "Başkan/Üst Onay tarafından iade edildi. Yayın kilidi devam ediyor."
    if not (getattr(target, "president_approved_at", None) or getattr(target, "president_approved_by_id", None)):
        return "Başkan onayı bekliyor. Başkan/Üst Onay şartı tamamlanmadan yayın yapılamaz. Başkan/Üst Onay Yayın Kilidi"
    try:
        sequence_no = int(getattr(target, "sequence_no", 1) or 1)
    except Exception:
        sequence_no = 1
    if sequence_no >= 2 and not (getattr(target, "administrative_process_started_at", None) or getattr(target, "administrative_process_started_by_id", None)):
        return "Tekrarlayan Düşük Performans Süreci başlatılmadan yayın yapılamaz. Sistem otomatik işten çıkarma yapmaz."
    if sequence_no < 2 and not (getattr(target, "warning_recorded_at", None) or getattr(target, "warning_recorded_by_id", None)):
        return "İlk düşük performans uyarısı oluşmadan yayın yapılamaz."
    return None


def _frozen_auto_record_fires(process) -> bool:
    if bool(getattr(process, "is_second_or_later", False)):
        return False
    if not (getattr(process, "president_approved_at", None) or getattr(process, "president_approved_by_id", None)):
        return False
    return not (getattr(process, "warning_recorded_at", None) or getattr(process, "warning_recorded_by_id", None))


def _frozen_auto_start_fires(process) -> bool:
    if not bool(getattr(process, "is_second_or_later", False)):
        return False
    if not (getattr(process, "president_approved_at", None) or getattr(process, "president_approved_by_id", None)):
        return False
    return not (getattr(process, "administrative_process_started_at", None) or getattr(process, "administrative_process_started_by_id", None))


def _frozen_sync_current_stage(process) -> tuple[str, str, str]:
    if getattr(process, "president_rejected_at", None):
        return ("president_rejected", "president_returned", "Başkan/Üst Onay tarafından iade edildi")
    if not getattr(process, "president_approved_at", None):
        return ("president_approval_pending", "president_approval_pending", "Başkan/Üst Onay Bekliyor")
    if getattr(process, "is_second_or_later", False):
        if getattr(process, "administrative_process_started_at", None):
            return ("second_low_repeat", "second_low_repeat", "Tekrarlayan Düşük Performans Süreci")
        return ("president_approved", "president_approved_pending_admin_process", "Başkan/Üst Onay sonrası idari süreç bekliyor")
    if getattr(process, "warning_recorded_at", None):
        return ("first_low_warning", "first_low_warning", "Düşük Performans Uyarısı Oluşturuldu")
    return ("president_approved", "president_approved_pending_warning", "Başkan/Üst Onay sonrası uyarı kaydı bekliyor")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def process_cls() -> Any:
    from app.models import PerformanceLowScoreProcess

    return PerformanceLowScoreProcess


@pytest.fixture(scope="module")
def svc() -> Any:
    from app.services.performance import low_score_process_service

    return low_score_process_service


def _policy_combos():
    for combo in itertools.product(*_POLICY_DOMAINS):
        yield dict(zip(_POLICY_FIELDS, combo, strict=True))


def _targets(process_cls):
    """One real model instance and one duck-typed object, re-filled per combo."""
    return (
        ("model", process_cls(final_total_100=_LOW_SCORE)),
        ("duck", SimpleNamespace(final_total_100=_LOW_SCORE)),
    )


def _fill(target, fields: dict[str, Any]) -> None:
    for name, value in fields.items():
        setattr(target, name, value)


# ---------------------------------------------------------------------------
# get_low_score_publish_block_reason: named scenarios
# ---------------------------------------------------------------------------


def test_block_reason_accepts_approved_by_id_without_approved_at(svc, process_cls) -> None:
    process = process_cls(final_total_100=_LOW_SCORE, sequence_no=1, president_approved_by_id=7, warning_recorded_at=_DT)
    assert process.is_president_approved is True
    assert svc.get_low_score_publish_block_reason(process=process, ensure=False) is None
    assert process.is_finalized_for_publish is True


@pytest.mark.parametrize(
    "rejection",
    [{"president_rejection_note": "Eksik gerekçe"}, {"president_rejected_by_id": 7}],
)
def test_block_reason_treats_rejection_note_or_rejector_id_alone_as_rejected(svc, process_cls, rejection) -> None:
    process = process_cls(
        final_total_100=_LOW_SCORE,
        sequence_no=1,
        president_approved_at=_DT,
        warning_recorded_at=_DT,
        **rejection,
    )
    assert process.is_president_rejected is True
    reason = svc.get_low_score_publish_block_reason(process=process, ensure=False)
    assert reason is not None
    assert "iade" in reason.lower()
    assert process.is_finalized_for_publish is False


@pytest.mark.parametrize("sequence_no", [2, 3, "2", 2.7])
def test_block_reason_repeated_low_score_requires_administrative_process(svc, process_cls, sequence_no) -> None:
    process = process_cls(final_total_100=_LOW_SCORE, sequence_no=sequence_no, president_approved_at=_DT, warning_recorded_at=_DT)
    assert process.is_second_or_later is True
    reason = svc.get_low_score_publish_block_reason(process=process, ensure=False)
    assert reason is not None
    assert "Tekrarlayan Düşük Performans Süreci" in reason

    process.administrative_process_started_by_id = 7
    assert svc.get_low_score_publish_block_reason(process=process, ensure=False) is None


def test_block_reason_unparseable_sequence_no_falls_back_to_first_low_score_and_logs(svc, process_cls, caplog) -> None:
    process = process_cls(final_total_100=_LOW_SCORE, sequence_no="bozuk", president_approved_at=_DT)
    with caplog.at_level(logging.ERROR):
        reason = svc.get_low_score_publish_block_reason(process=process, ensure=False)
    assert reason == "İlk düşük performans uyarısı oluşmadan yayın yapılamaz."
    # The parse failure is logged, not swallowed silently.
    assert any(record.levelno == logging.ERROR for record in caplog.records)


def test_block_reason_duck_typed_process_without_optional_fields(svc) -> None:
    # Same shape as test_phase4t_publish_block_reason_for_direct_process_states:
    # no *_by_id, no rejection note, no sequence_no attribute at all.
    released = SimpleNamespace(
        final_total_100=60,
        president_rejected_at=None,
        president_approved_at=object(),
        process_type="first_low_score_warning",
        administrative_process_started_at=None,
        warning_recorded_at=object(),
    )
    assert svc.get_low_score_publish_block_reason(process=released, ensure=False) is None
    pending = SimpleNamespace(**{**vars(released), "president_approved_at": None})
    assert "Başkan" in svc.get_low_score_publish_block_reason(process=pending, ensure=False)


# ---------------------------------------------------------------------------
# get_low_score_publish_block_reason: sweeps
# ---------------------------------------------------------------------------


def test_block_reason_matches_frozen_policy_across_input_domain(svc, process_cls) -> None:
    targets = _targets(process_cls)
    checked = 0
    mismatches: list[tuple[str, dict[str, Any], Any, Any]] = []
    for fields in _policy_combos():
        for kind, target in targets:
            _fill(target, fields)
            actual = svc.get_low_score_publish_block_reason(process=target, ensure=False)
            expected = _frozen_publish_block_reason(target)
            if actual != expected:
                mismatches.append((kind, fields, actual, expected))
        checked += 1
    assert checked == _POLICY_DOMAIN_SIZE
    assert mismatches[:10] == []


def test_block_reason_is_released_exactly_when_model_is_finalized_for_publish(svc, process_cls) -> None:
    process = process_cls(final_total_100=_LOW_SCORE)
    disagreements: list[dict[str, Any]] = []
    for fields in _policy_combos():
        _fill(process, fields)
        released = svc.get_low_score_publish_block_reason(process=process, ensure=False) is None
        if released != process.is_finalized_for_publish:
            disagreements.append(fields)
    assert disagreements[:10] == []


@pytest.mark.parametrize("final_total_100", [None, 0, -5, 69.99, 70, 70.0, 85, "bozuk"])
def test_block_reason_score_guard_matches_frozen_policy(svc, process_cls, final_total_100) -> None:
    for fields in (
        {},
        {"president_rejected_at": _DT},
        {"president_approved_at": _DT, "sequence_no": 1},
        {"president_approved_at": _DT, "sequence_no": 2, "administrative_process_started_at": _DT},
    ):
        process = process_cls(final_total_100=final_total_100, **fields)
        assert svc.get_low_score_publish_block_reason(process=process, ensure=False) == _frozen_publish_block_reason(process)


# ---------------------------------------------------------------------------
# auto_record_first_low_score_warning / auto_start_second_low_score_process:
# the approval gate that decides whether the next step fires
# ---------------------------------------------------------------------------


def _gate_combos(completion_fields: tuple[str, str]):
    names = ("president_approved_at", "president_approved_by_id", "sequence_no", *completion_fields)
    domains = ((None, _DT), (None, 0, 7), _SEQUENCE_DOMAIN, (None, _DT), (None, 0, 7))
    for combo in itertools.product(*domains):
        yield dict(zip(names, combo, strict=True))


@pytest.mark.parametrize(
    ("entry_point", "step_function", "completion_fields", "oracle"),
    [
        (
            "auto_record_first_low_score_warning",
            "record_first_warning",
            ("warning_recorded_at", "warning_recorded_by_id"),
            _frozen_auto_record_fires,
        ),
        (
            "auto_start_second_low_score_process",
            "start_second_repeat_admin_process",
            ("administrative_process_started_at", "administrative_process_started_by_id"),
            _frozen_auto_start_fires,
        ),
    ],
)
def test_auto_step_approval_gate_matches_frozen_policy(
    svc, process_cls, monkeypatch, entry_point, step_function, completion_fields, oracle
) -> None:
    calls: list[Any] = []
    sentinel = object()

    def _record_call(process, **kwargs):
        calls.append(process)
        return sentinel

    monkeypatch.setattr(svc, step_function, _record_call)
    auto_step = getattr(svc, entry_point)

    mismatches: list[tuple[str, dict[str, Any], bool, bool]] = []
    checked = 0
    for fields in _gate_combos(completion_fields):
        for kind, target in (
            ("model", process_cls(final_total_100=_LOW_SCORE, **fields)),
            ("duck", SimpleNamespace(final_total_100=_LOW_SCORE, **fields)),
        ):
            calls.clear()
            result = auto_step(target)
            fired = bool(calls)
            expected = oracle(target)
            consistent = (result is sentinel and calls == [target]) if fired else (result is target and not calls)
            if fired != expected or not consistent:
                mismatches.append((kind, fields, fired, expected))
        checked += 1
    assert checked == 2 * 3 * len(_SEQUENCE_DOMAIN) * 2 * 3
    assert mismatches[:10] == []


def test_auto_record_fires_for_approver_id_without_approved_at(svc, process_cls, monkeypatch) -> None:
    calls: list[Any] = []

    def _record_call(process, **kwargs):
        calls.append(process)
        return process

    monkeypatch.setattr(svc, "record_first_warning", _record_call)
    process = process_cls(final_total_100=_LOW_SCORE, sequence_no=1, president_approved_by_id=7)
    svc.auto_record_first_low_score_warning(process)
    assert calls == [process]


def test_auto_start_fires_for_approver_id_without_approved_at(svc, process_cls, monkeypatch) -> None:
    calls: list[Any] = []

    def _record_call(process, **kwargs):
        calls.append(process)
        return process

    monkeypatch.setattr(svc, "start_second_repeat_admin_process", _record_call)
    process = process_cls(final_total_100=_LOW_SCORE, sequence_no=2, president_approved_by_id=7)
    svc.auto_start_second_low_score_process(process)
    assert calls == [process]


# ---------------------------------------------------------------------------
# _sync_current_stage: status / current_stage_key / current_owner_label
# ---------------------------------------------------------------------------


def test_sync_current_stage_matches_frozen_policy_across_input_domain(svc, process_cls) -> None:
    targets = _targets(process_cls)
    checked = 0
    mismatches: list[tuple[str, dict[str, Any], tuple[Any, ...], tuple[str, str, str]]] = []
    for fields in _policy_combos():
        for kind, target in targets:
            _fill(target, fields)
            expected = _frozen_sync_current_stage(target)
            returned = svc._sync_current_stage(target)
            actual = (target.status, target.current_stage_key, target.current_owner_label)
            if returned is not target or actual != expected:
                mismatches.append((kind, fields, actual, expected))
        checked += 1
    assert checked == _POLICY_DOMAIN_SIZE
    assert mismatches[:10] == []


def test_sync_current_stage_reads_only_timestamps_for_approval_and_rejection(svc, process_cls) -> None:
    """Characterizes a known divergence (reported as a P0.1 finding): stage
    sync decides approval/rejection from the *_at timestamps only, while the
    canonical model policy also accepts the approver/rejector id and the
    rejection note. Both write paths (president_approve_process /
    president_reject_process) always set the timestamp, so the two agree for
    every state the live flows produce. Unifying them is a behavior change
    and must be done deliberately, updating this test."""
    note_only = process_cls(sequence_no=1, president_rejection_note="İade")
    svc._sync_current_stage(note_only)
    assert note_only.is_president_rejected is True
    assert note_only.status == "president_approval_pending"

    approver_only = process_cls(sequence_no=1, president_approved_by_id=7)
    svc._sync_current_stage(approver_only)
    assert approver_only.is_president_approved is True
    assert approver_only.status == "president_approval_pending"
