"""BYS360 H1E-N -- 5 more raw-status leaks found in Section 14's fresh
repo-wide re-audit (a second grep pass, after the H1E-N1/N2/N3 sub-waves
had already landed, for the sibling shape `X_LABELS.get(raw, raw or
"default")` -- functionally identical to `X_LABELS.get(raw, raw)`
whenever `raw` is a non-empty string, since `raw or "default"` then just
evaluates to `raw` itself).

  - app/performance/feedback_helpers.py's _notify_feedback_meeting_updated()
    built a real Notification's TITLE
    (f"Geri bildirim görüşmesi güncellendi | {status_label}") from
    `status_label_map.get(meeting_status_value, meeting_status_value or
    "Güncellendi")` -- a genuinely unmapped FeedbackMeeting.status value
    would show up raw in a real user's notification.
  - app/services/performance/feedback_audit_service.py and
    feedback_ops_service.py each have their OWN independent, near-
    identical `_status_label()` (same ~12-value vocabulary, one subtle
    wording drift already present: "randevu_iptal" -> "Randevu iptal
    edildi" vs "Randevu iptal" -- not touched here, flagged only) with
    the identical `labels.get(raw, raw or "-")` shape. Fixed both
    fallbacks independently; NOT consolidated into one dict in this
    wave (architectural follow-up, matching the established H1E-D
    precedent of flagging rather than force-merging drifted duplicate
    dictionaries).
  - app/services/performance/meeting_p4_development_guidance.py has the
    identical `P4_TYPE_LABELS.get(recommendation_type, recommendation_type
    or "Gelişim Önerisi")` shape at two independent call sites
    (_recommendation_rows_for_evaluation and
    build_p4_development_guidance_context), both feeding a
    `row["type_label"]` field rendered to a manager/employee reviewing
    development recommendations. (Both sites were later retired together
    with the legacy P4 recommendation contract; the scorecard now renders
    the canonical Phase-10 normalizer's label, which the test below pins.)
  - app/services/performance/phase7_scorecard_archive_center.py's
    phase7_status_label() had `STATUS_LABELS.get(text, text or "Arşiv
    Durumu Belirtilmedi")`, feeding the scorecard archive center's
    status column.

Every fix here only changes the "value present but unmapped" fallback
branch -- the existing empty/missing-value default text ("Güncellendi",
"-", "Gelişim Önerisi", "Arşiv Durumu Belirtilmedi") is preserved
exactly, since it already applied cleanly to that case via the `or`
short-circuit and was never itself an anti-pattern.

Writes NOTHING to any production source file (the meeting-notification
test monkeypatches notify_user() rather than touching the DB).
"""
from __future__ import annotations

from types import SimpleNamespace


def test_feedback_audit_service_status_label_never_leaks_raw() -> None:
    from app.services.performance.feedback_audit_service import _status_label

    assert _status_label("bekliyor") == "Bekliyor"
    assert _status_label("randevulandi") == "Randevulandı"
    assert _status_label("future_audit_status_v9") == "Bilinmiyor"
    assert _status_label(None) == "-"
    assert _status_label("") == "-"


def test_feedback_ops_service_status_label_never_leaks_raw() -> None:
    from app.services.performance.feedback_ops_service import _status_label

    assert _status_label("bekliyor") == "Bekliyor"
    assert _status_label("planlandi") == "Planlandı"
    assert _status_label("future_ops_status_v9") == "Bilinmiyor"
    assert _status_label(None) == "-"
    assert _status_label("") == "-"


def test_phase7_status_label_never_leaks_raw() -> None:
    from app.services.performance.phase7_scorecard_archive_center import phase7_status_label

    # Confirm a couple of known values still resolve via the dict (exact
    # keys depend on STATUS_LABELS' own contents; the empty/unmapped
    # contract below is what this fix actually changes).
    assert phase7_status_label("future_archive_status_v9") == "Arşiv Durumu Belirtilmedi"
    assert phase7_status_label(None) == "Arşiv Durumu Belirtilmedi"
    assert phase7_status_label("") == "Arşiv Durumu Belirtilmedi"
    assert phase7_status_label("future_archive_status_v9") != "future_archive_status_v9"


def test_scorecard_recommendation_rows_never_leak_raw_type() -> None:
    # The scorecard's development recommendations now come only from the canonical
    # Phase-10 contract (the legacy P4 type vocabulary is retired); its normalizer
    # owns the type label shown to managers and employees.
    from app.performance.phase10_development_guidance_ui import (
        TYPE_LABELS,
        normalize_recommendation,
    )

    unknown = normalize_recommendation({"recommendation_type": "future_recommendation_type_v9"})
    assert unknown["recommendation_type_label"] == "Gelişim Planı"
    assert unknown["recommendation_type_label"] != "future_recommendation_type_v9"

    for known_key, known_label in TYPE_LABELS.items():
        assert normalize_recommendation({"recommendation_type": known_key})["recommendation_type_label"] == known_label


def test_notify_feedback_meeting_updated_notification_title_never_leaks_raw_status(monkeypatch) -> None:
    from app.performance import feedback_helpers

    captured: dict = {}

    def _fake_notify_user(user_id, *, title, body, **kwargs):
        captured["user_id"] = user_id
        captured["title"] = title
        captured["body"] = body

    monkeypatch.setattr(feedback_helpers, "notify_user", _fake_notify_user)
    monkeypatch.setattr(feedback_helpers, "url_for", lambda *a, **k: "/feedback/meeting/1")
    monkeypatch.setattr(feedback_helpers, "_feedback_manager_ids", lambda feedback_request: set())

    meeting = SimpleNamespace(
        id=1,
        employee=SimpleNamespace(full_name="Test Personel"),
        meeting_date=None,
        meeting_start=None,
        meeting_end=None,
        status="future_meeting_status_v9",
        feedback_request=None,
        manager_id=42,
    )

    feedback_helpers._notify_feedback_meeting_updated(meeting)

    assert "future_meeting_status_v9" not in captured["title"]
    assert "Güncellendi" in captured["title"]
    # The raw stored meeting.status attribute itself is never touched.
    assert meeting.status == "future_meeting_status_v9"


def test_notify_feedback_meeting_updated_known_status_shows_turkish_label(monkeypatch) -> None:
    from app.performance import feedback_helpers

    captured: dict = {}

    def _fake_notify_user(user_id, *, title, body, **kwargs):
        captured["title"] = title

    monkeypatch.setattr(feedback_helpers, "notify_user", _fake_notify_user)
    monkeypatch.setattr(feedback_helpers, "url_for", lambda *a, **k: "/feedback/meeting/1")
    monkeypatch.setattr(feedback_helpers, "_feedback_manager_ids", lambda feedback_request: set())

    meeting = SimpleNamespace(
        id=1,
        employee=SimpleNamespace(full_name="Test Personel"),
        meeting_date=None,
        meeting_start=None,
        meeting_end=None,
        status="planlandi",
        feedback_request=None,
        manager_id=42,
    )

    feedback_helpers._notify_feedback_meeting_updated(meeting)

    assert "Planlandı" in captured["title"]
