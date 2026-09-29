from __future__ import annotations

from datetime import datetime

from flask import current_app

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import AIFeedbackLog, AIRecommendation, AIRequestLog, AISummaryCache
from app.services.ai.guardrails import AIInputError, AIResourceNotFound
from app.services.ai.redaction import redact_text
from app.services.ai.schema_guard import ai_schema_ready

VALID_RECOMMENDATION_STATUSES = {"open", "accepted", "rejected", "dismissed"}


def _prepare_log_text(value: str | None, *, enabled: bool) -> str | None:
    if not enabled:
        return None
    text = redact_text(value or "").strip()
    if not text:
        return None
    limit = int(current_app.config.get("AI_MAX_INPUT_CHARS", 12000) or 12000)
    return text[:limit]


def log_ai_request(
    *,
    module_type: str,
    feature_type: str,
    target_table: str | None,
    target_id: int | None,
    user_id: int | None,
    request_text: str | None,
    response_text: str | None,
    provider_name: str | None,
    model_name: str | None,
    prompt_version: str | None,
    latency_ms: int | None = None,
    token_in: int | None = None,
    token_out: int | None = None,
    was_masked: bool = True,
    was_user_visible: bool = True,
    status: str = "completed",
    error_message: str | None = None,
) -> AIRequestLog | None:
    if not ai_schema_ready():
        return None
    row = AIRequestLog(
        module_type=module_type,
        feature_type=feature_type,
        target_table=target_table,
        target_id=target_id,
        user_id=user_id,
        request_text=_prepare_log_text(request_text, enabled=bool(current_app.config.get("AI_LOG_REQUEST_TEXT", True))),
        response_text=_prepare_log_text(response_text, enabled=bool(current_app.config.get("AI_LOG_RESPONSE_TEXT", True))),
        provider_name=provider_name,
        model_name=model_name,
        prompt_version=prompt_version,
        latency_ms=latency_ms,
        token_in=token_in,
        token_out=token_out,
        was_masked=bool(was_masked),
        was_user_visible=was_user_visible,
        status=status,
        error_message=(error_message or "").strip() or None,
    )
    db.session.add(row)
    db.session.flush()
    return row


def ensure_recommendation_rows(
    *,
    module_type: str,
    target_table: str,
    target_id: int,
    recommendation_type: str,
    titles: list[str],
    ai_request_log_id: int | None,
    created_by_id: int | None,
    severity: str = "warning",
) -> list[AIRecommendation]:
    created: list[AIRecommendation] = []
    if not ai_schema_ready():
        return created
    normalized_titles = [str(title).strip() for title in titles if str(title).strip()]
    if not normalized_titles:
        return created

    existing = {
        row.title.strip().lower()
        for row in AIRecommendation.query.filter_by(
            module_type=module_type,
            target_table=target_table,
            target_id=target_id,
            recommendation_type=recommendation_type,
        ).filter(AIRecommendation.status.in_(["open", "accepted"]))
    }

    for title in normalized_titles:
        key = title.lower()
        if key in existing:
            continue
        row = AIRecommendation(
            module_type=module_type,
            target_table=target_table,
            target_id=target_id,
            recommendation_type=recommendation_type,
            title=title,
            body=title,
            severity=severity,
            status="open",
            ai_request_log_id=ai_request_log_id,
            created_by_id=created_by_id,
            updated_by_id=created_by_id,
        )
        db.session.add(row)
        created.append(row)
        existing.add(key)
    if created:
        db.session.flush()
    return created


def mark_recommendation(recommendation_id: int, *, status: str, reviewed_by_user_id: int | None) -> AIRecommendation:
    normalized_status = (status or "").strip().lower()
    if normalized_status not in VALID_RECOMMENDATION_STATUSES:
        raise ValueError("Geçersiz AI öneri durumu.")
    recommendation = db.session.get(AIRecommendation, recommendation_id)
    if recommendation is None:
        raise LookupError("AI öneri kaydı bulunamadı.")
    recommendation.status = normalized_status
    recommendation.reviewed_by_user_id = reviewed_by_user_id
    recommendation.reviewed_at = utc_now()
    return recommendation


def log_ai_feedback(
    ai_request_log_id: int,
    *,
    user_id: int | None,
    feedback_type: str,
    feedback_note: str | None = None,
) -> AIFeedbackLog | None:
    if not ai_schema_ready():
        return None
    clean_type = (feedback_type or "").strip().lower() or "helpful"
    if len(clean_type) > AIFeedbackLog.__table__.c.feedback_type.type.length:
        raise AIInputError("Geri bildirim tipi çok uzun.")
    if db.session.get(AIRequestLog, ai_request_log_id) is None:
        raise AIResourceNotFound("AI istek kaydı bulunamadı.")
    row = AIFeedbackLog(
        ai_request_log_id=ai_request_log_id,
        user_id=user_id,
        feedback_type=clean_type,
        feedback_note=(feedback_note or "").strip() or None,
    )
    db.session.add(row)
    db.session.flush()
    return row


def upsert_ai_summary_cache(
    *,
    module_type: str,
    target_table: str,
    target_id: int,
    summary_kind: str,
    summary_text: str,
    source_hash: str | None = None,
    expires_at: datetime | None = None,
) -> AISummaryCache | None:
    if not ai_schema_ready():
        return None
    row = AISummaryCache.query.filter_by(
        module_type=(module_type or '').strip().lower(),
        target_table=(target_table or '').strip(),
        target_id=int(target_id or 0),
        summary_kind=(summary_kind or '').strip().lower(),
    ).first()
    if row is None:
        row = AISummaryCache(
            module_type=(module_type or '').strip().lower(),
            target_table=(target_table or '').strip(),
            target_id=int(target_id or 0),
            summary_kind=(summary_kind or '').strip().lower(),
        )
    row.summary_text = (summary_text or '').strip() or '-'
    row.source_hash = (source_hash or '').strip() or None
    row.expires_at = expires_at
    db.session.add(row)
    db.session.flush()
    return row


def cache_summary(*args, **kwargs):
    """Backward-compatible alias for preflight checks and older callers."""
    return upsert_ai_summary_cache(*args, **kwargs)
