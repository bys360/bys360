from __future__ import annotations

import csv
import io
import logging
from collections.abc import Sequence
from typing import Any

from flask import flash, make_response, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.core.datetime_utils import utc_now
from app.extensions import db
from app.models import (
    AIFeedbackLog,
    AIRecommendation,
    AIRedactionRule,
    AIRequestLog,
    AISummaryCache,
)
from app.route_registry import main_bp
from app.route_support import admin_required, menu_key_required, safe_render
from app.services.ai.audit import mark_recommendation
from app.services.ai.client import get_provider_snapshot
from app.services.ai.module_scope import (
    REMOVED_AI_MODULES,
    ai_module_focus,
    ai_module_label,
    ai_module_tables,
    hidden_ai_modules,
    is_live_ai_module,
    live_ai_modules,
    normalize_ai_module,
    scope_visible_modules,
    visible_module_options,
)
from app.services.ai.preflight import build_ai_preflight_snapshot
from app.services.ai.schema_guard import get_ai_schema_status
from app.services.ai.smoke import build_ai_smoke_snapshot
from app.services.sql_refactor_query_helpers import (
    distinct_non_empty_values,
    distinct_normalized_non_empty_values,
)

logger = logging.getLogger(__name__)

KNOWN_AI_MODULES: tuple[str, ...] = live_ai_modules(include_system=True)


def _module_key(module_type: str | None) -> str:
    return normalize_ai_module(module_type)


def _module_label(module_type: str | None) -> str:
    return ai_module_label(module_type)


def _safe_int(value: str | None, default: int = 1) -> int:
    try:
        return max(int(value or default), 1)
    except (TypeError, ValueError):
        return default


def _status_counts(query, model, field_name: str = "status") -> dict[str, int]:
    field = getattr(model, field_name)
    rows = query.with_entities(field, func.count(model.id)).group_by(field).all()
    return {str(key or "belirsiz"): int(count or 0) for key, count in rows}


def _module_counts(query, model) -> list[dict[str, int | str]]:
    rows = (
        query.with_entities(model.module_type, func.count(model.id))
        .group_by(model.module_type)
        .order_by(func.count(model.id).desc(), model.module_type.asc())
        .limit(8)
        .all()
    )
    return [{"label": str(key or "genel"), "value": int(count or 0)} for key, count in rows]


def _top_feedback_types() -> list[dict[str, int | str]]:
    rows = (
        _live_feedback_query()
        .with_entities(AIFeedbackLog.feedback_type, func.count(AIFeedbackLog.id))
        .group_by(AIFeedbackLog.feedback_type)
        .order_by(func.count(AIFeedbackLog.id).desc(), AIFeedbackLog.feedback_type.asc())
        .limit(6)
        .all()
    )
    return [{"label": str(key or "feedback"), "value": int(count or 0)} for key, count in rows]


def _prompt_version_counts(query) -> list[dict[str, int | str]]:
    rows = (
        query.with_entities(AIRequestLog.prompt_version, func.count(AIRequestLog.id))
        .group_by(AIRequestLog.prompt_version)
        .order_by(func.count(AIRequestLog.id).desc(), AIRequestLog.prompt_version.asc())
        .limit(8)
        .all()
    )
    return [{"label": str(key or "tanımsız"), "value": int(count or 0)} for key, count in rows]


def _safe_ratio(part: int, whole: int) -> int:
    if not whole:
        return 0
    return int(round((part / whole) * 100))


def _live_request_query():
    return scope_visible_modules(AIRequestLog.query, AIRequestLog.module_type)


def _live_recommendation_query():
    return scope_visible_modules(AIRecommendation.query, AIRecommendation.module_type)


def _live_cache_query():
    return scope_visible_modules(AISummaryCache.query, AISummaryCache.module_type)


def _live_rule_query():
    return scope_visible_modules(AIRedactionRule.query, AIRedactionRule.module_type)


def _live_feedback_query():
    return (
        AIFeedbackLog.query
        .join(AIRequestLog, AIFeedbackLog.ai_request_log_id == AIRequestLog.id)
        .filter(func.lower(func.coalesce(AIRequestLog.module_type, "")).in_(list(live_ai_modules(include_system=True))))
    )


def _count_hidden_legacy_requests() -> int:
    return int(
        AIRequestLog.query
        .filter(func.lower(func.coalesce(AIRequestLog.module_type, "")).in_(list(hidden_ai_modules())))
        .count()
        or 0
    )


def _normalize_selected_module(value: str | None) -> str:
    key = _module_key(value)
    return key if key and is_live_ai_module(key) else ""


def _render_ai_schema_not_ready(*, page_title: str, selected_module_type: str = ""):
    schema_status = get_ai_schema_status()
    return safe_render(
        "admin_ai_schema_not_ready.html",
        page_title=page_title,
        selected_module_type=selected_module_type,
        ai_schema_status=schema_status,
        module_options=_all_ai_modules(),
    )


def _build_health_actions(summary: dict[str, Any]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    failed_requests = int(summary.get("failed_requests") or 0)
    unmasked_requests = int(summary.get("unmasked_requests") or 0)
    open_recommendations = int(summary.get("open_recommendations") or 0)
    active_rules = int(summary.get("active_rules") or 0)
    feedback_negative = int(summary.get("feedback_negative") or 0)

    if failed_requests > 0:
        actions.append(
            {
                "tone": "warning",
                "title": "Hata veren AI çağrıları var",
                "body": f"{failed_requests} işlem warning/failed durumunda. Önce AI işlem günlüklerini filtreleyip problemli kayıtları ayırın.",
                "href": url_for("main.admin_ai_requests", status="failed"),
                "label": "Problemli işlemleri aç",
            }
        )
    if unmasked_requests > 0:
        actions.append(
            {
                "tone": "warning",
                "title": "Maskesiz kayıtlar görünüyor",
                "body": f"{unmasked_requests} AI kaydı maskeleme uygulanmadan üretilmiş. Redaction kurallarını gözden geçirmek güvenli olur.",
                "href": url_for("main.admin_ai_redaction_rules"),
                "label": "Maskeleme kurallarına git",
            }
        )
    if active_rules == 0:
        actions.append(
            {
                "tone": "warning",
                "title": "Aktif redaction kuralı yok",
                "body": "AI özetleri kullanıma açıkken maskeleme kuralı tanımlı değil. En azından kritik alanlar için temel kuralları ekleyin.",
                "href": url_for("main.admin_ai_redaction_rules"),
                "label": "Kural tanımla",
            }
        )
    if open_recommendations > 0:
        actions.append(
            {
                "tone": "calm",
                "title": "Bekleyen AI önerileri var",
                "body": f"{open_recommendations} öneri hâlâ açık. Yönetici kararına bağlanmayan kayıtlar birikmeye başlamış olabilir.",
                "href": url_for("main.admin_ai_recommendations", status="open"),
                "label": "Açık önerileri incele",
            }
        )
    if feedback_negative > 0:
        actions.append(
            {
                "tone": "warning",
                "title": "Olumsuz kullanıcı geri bildirimi geldi",
                "body": f"{feedback_negative} kayıt yararsız/yanlış geri bildirimi aldı. Prompt sürümü ve çıktı kalitesini kontrol etmek iyi olur.",
                "href": url_for("main.admin_ai_feedback", feedback_type="not_helpful"),
                "label": "Geri bildirimleri aç",
            }
        )
    if not actions:
        actions.append(
            {
                "tone": "success",
                "title": "AI yönetim görünümü dengeli",
                "body": "Şu an kritik hata, maskesiz kayıt veya negatif geri bildirim baskısı görünmüyor. Bir sonraki adım kullanım yayılımını artırmak olabilir.",
                "href": url_for("main.admin_ai_requests"),
                "label": "İşlem günlüklerini aç",
            }
        )
    return actions[:4]


def _request_filters(base_query):
    module_type = _normalize_selected_module(request.args.get("module_type"))
    feature_type = (request.args.get("feature_type") or "").strip().lower()
    status = (request.args.get("status") or "").strip().lower()
    prompt_version = (request.args.get("prompt_version") or "").strip().lower()
    masked_state = (request.args.get("masked_state") or "").strip().lower()
    if module_type:
        base_query = base_query.filter(func.lower(AIRequestLog.module_type) == module_type)
    if feature_type:
        base_query = base_query.filter(func.lower(AIRequestLog.feature_type) == feature_type)
    if status:
        base_query = base_query.filter(func.lower(AIRequestLog.status) == status)
    if prompt_version:
        base_query = base_query.filter(func.lower(func.coalesce(AIRequestLog.prompt_version, "tanimsiz")) == prompt_version)
    if masked_state == "masked":
        base_query = base_query.filter(AIRequestLog.was_masked.is_(True))
    elif masked_state == "unmasked":
        base_query = base_query.filter(AIRequestLog.was_masked.is_(False))
    return base_query, module_type, feature_type, status, prompt_version, masked_state


def _recommendation_filters(base_query):
    module_type = _normalize_selected_module(request.args.get("module_type"))
    severity = (request.args.get("severity") or "").strip().lower()
    status = (request.args.get("status") or "").strip().lower()
    if module_type:
        base_query = base_query.filter(func.lower(AIRecommendation.module_type) == module_type)
    if severity:
        base_query = base_query.filter(func.lower(AIRecommendation.severity) == severity)
    if status:
        base_query = base_query.filter(func.lower(AIRecommendation.status) == status)
    return base_query, module_type, severity, status


def _feedback_filters(base_query):
    feedback_type = (request.args.get("feedback_type") or "").strip().lower()
    module_type = _normalize_selected_module(request.args.get("module_type"))
    if feedback_type:
        base_query = base_query.filter(func.lower(AIFeedbackLog.feedback_type) == feedback_type)
    if module_type:
        base_query = base_query.filter(func.lower(AIRequestLog.module_type) == module_type)
    return base_query, feedback_type, module_type


def _redaction_choices() -> dict[str, list[str]]:
    modules = visible_module_options(distinct_non_empty_values(AIRedactionRule.module_type))
    field_names = distinct_non_empty_values(AIRedactionRule.field_name)
    return {"modules": modules, "field_names": field_names}

def _all_ai_modules() -> list[str]:
    values: set[str] = set(KNOWN_AI_MODULES)
    for column in (
        AIRequestLog.module_type,
        AIRecommendation.module_type,
        AIRedactionRule.module_type,
        AISummaryCache.module_type,
    ):
        values.update(distinct_normalized_non_empty_values(column))
    return visible_module_options(values)

def _module_health_rows(selected_module_type: str | None = None) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    for module in _all_ai_modules():
        if selected_module_type and module != selected_module_type:
            continue
        request_query = AIRequestLog.query.filter(func.lower(AIRequestLog.module_type) == module)
        recommendation_query = AIRecommendation.query.filter(func.lower(AIRecommendation.module_type) == module)
        cache_query = AISummaryCache.query.filter(func.lower(AISummaryCache.module_type) == module)
        rule_query = AIRedactionRule.query.filter(func.lower(AIRedactionRule.module_type) == module)

        request_total = request_query.count()
        failed_total = request_query.filter(AIRequestLog.status.in_(['failed', 'warning'])).count()
        masked_total = request_query.filter(AIRequestLog.was_masked.is_(True)).count()
        unmasked_total = request_query.filter(AIRequestLog.was_masked.is_(False)).count()
        avg_latency_ms = int(db.session.query(func.avg(AIRequestLog.latency_ms)).filter(func.lower(AIRequestLog.module_type) == module).scalar() or 0)
        latest_request = request_query.order_by(AIRequestLog.created_at.desc()).first()
        latest_prompt_version = getattr(latest_request, 'prompt_version', None) or '-'
        feedback_total = (
            db.session.query(func.count(AIFeedbackLog.id))
            .join(AIRequestLog, AIFeedbackLog.ai_request_log_id == AIRequestLog.id)
            .filter(func.lower(AIRequestLog.module_type) == module)
            .scalar()
            or 0
        )
        negative_feedback = (
            db.session.query(func.count(AIFeedbackLog.id))
            .join(AIRequestLog, AIFeedbackLog.ai_request_log_id == AIRequestLog.id)
            .filter(
                func.lower(AIRequestLog.module_type) == module,
                AIFeedbackLog.feedback_type.in_(['not_helpful', 'wrong', 'unsafe']),
            )
            .scalar()
            or 0
        )
        recommendation_total = recommendation_query.count()
        open_recommendations = recommendation_query.filter(AIRecommendation.status == 'open').count()
        active_rules = rule_query.filter(AIRedactionRule.is_active.is_(True)).count()
        cache_total = cache_query.count()
        latest_cache = cache_query.order_by(AISummaryCache.updated_at.desc(), AISummaryCache.created_at.desc()).first()
        latest_cache_kind = getattr(latest_cache, 'summary_kind', None) or '-'

        visible_footprint = request_total + cache_total + recommendation_total
        risk_score = int(failed_total * 5 + unmasked_total * 6 + negative_feedback * 4 + open_recommendations * 2)
        if visible_footprint and active_rules == 0:
            risk_score += 3
        if request_total and masked_total == 0:
            risk_score += 2
        if unmasked_total or failed_total:
            tone = 'critical'
        elif negative_feedback or open_recommendations or (visible_footprint and active_rules == 0):
            tone = 'warning'
        else:
            tone = 'calm'

        if unmasked_total:
            next_step = 'Maskeleme kuralı ve bu modülün görünür alanlarını kontrol edin.'
        elif failed_total:
            next_step = 'Hatalı AI kayıtlarını açıp prompt ve veri akışını gözden geçirin.'
        elif open_recommendations:
            next_step = 'Açık AI önerilerini yönetici kararıyla kapatın.'
        elif negative_feedback:
            next_step = 'Olumsuz geri bildirim alan çıktı örneklerini prompt sürümüne göre ayırın.'
        elif visible_footprint and active_rules == 0:
            next_step = 'Bu modül için en az bir aktif redaction kuralı tanımlayın.'
        elif cache_total and not request_total:
            next_step = 'Özet cache var; görünür AI çağrıları gerekiyorsa kontrollü kullanım rotalarını açın.'
        else:
            next_step = 'Görünüm dengeli; düzenli bakım ve sürüm takibi yeterli.'

        rows.append(
            {
                'module_type': module,
                'module_label': _module_label(module),
                'request_total': int(request_total or 0),
                'failed_total': int(failed_total or 0),
                'masked_total': int(masked_total or 0),
                'unmasked_total': int(unmasked_total or 0),
                'masked_rate': _safe_ratio(int(masked_total or 0), int(request_total or 0)),
                'feedback_total': int(feedback_total or 0),
                'negative_feedback': int(negative_feedback or 0),
                'recommendation_total': int(recommendation_total or 0),
                'open_recommendations': int(open_recommendations or 0),
                'active_rules': int(active_rules or 0),
                'cache_total': int(cache_total or 0),
                'avg_latency_ms': int(avg_latency_ms or 0),
                'latest_prompt_version': latest_prompt_version,
                'latest_cache_kind': latest_cache_kind,
                'risk_score': risk_score,
                'tone': tone,
                'next_step': next_step,
            }
        )
    return sorted(rows, key=lambda item: (-int(item.get('risk_score') or 0), -int(item.get('request_total') or 0), -int(item.get('cache_total') or 0), str(item.get('module_type') or '')))


def _feature_focus_text(module_type: str, feature_counts: Sequence[tuple[str | None, int]]) -> str:
    top = [str(name or '-').strip() for name, _count in feature_counts[:3] if str(name or '').strip()]
    if top:
        return ', '.join(top)
    return ai_module_focus(module_type)


def _operations_report_rows(selected_module_type: str | None = None) -> list[dict[str, int | str | None]]:
    module_health_map = {str(row.get('module_type') or ''): row for row in _module_health_rows()}
    rows: list[dict[str, int | str | None]] = []
    for module in _all_ai_modules():
        if selected_module_type and module != selected_module_type:
            continue

        request_query = AIRequestLog.query.filter(func.lower(AIRequestLog.module_type) == module)
        recommendation_query = AIRecommendation.query.filter(func.lower(AIRecommendation.module_type) == module)
        cache_query = AISummaryCache.query.filter(func.lower(AISummaryCache.module_type) == module)

        request_total = int(request_query.count() or 0)
        visible_request_total = int(request_query.filter(AIRequestLog.was_user_visible.is_(True)).count() or 0)
        failed_total = int(request_query.filter(AIRequestLog.status.in_(['failed', 'warning'])).count() or 0)
        feature_rows = [
            (str(name or '').strip(), int(count or 0))
            for name, count in request_query.with_entities(AIRequestLog.feature_type, func.count(AIRequestLog.id))
            .group_by(AIRequestLog.feature_type)
            .order_by(func.count(AIRequestLog.id).desc(), AIRequestLog.feature_type.asc())
            .all()
        ]
        report_request_total = sum(
            count
            for name, count in feature_rows
            if any(token in (name or '').lower() for token in ['report', 'export', 'summary', 'recommendation'])
        )
        recommendation_total = int(recommendation_query.count() or 0)
        open_recommendations = int(recommendation_query.filter(AIRecommendation.status == 'open').count() or 0)
        negative_feedback = int(
            db.session.query(func.count(AIFeedbackLog.id))
            .join(AIRequestLog, AIFeedbackLog.ai_request_log_id == AIRequestLog.id)
            .filter(
                func.lower(AIRequestLog.module_type) == module,
                AIFeedbackLog.feedback_type.in_(['not_helpful', 'wrong', 'unsafe']),
            )
            .scalar()
            or 0
        )
        cache_total = int(cache_query.count() or 0)

        latest_request = request_query.order_by(AIRequestLog.created_at.desc()).first()
        latest_recommendation = recommendation_query.order_by(AIRecommendation.created_at.desc()).first()
        latest_cache = cache_query.order_by(AISummaryCache.updated_at.desc(), AISummaryCache.created_at.desc()).first()
        latest_activity = max(
            [
                value
                for value in [
                    getattr(latest_request, 'created_at', None),
                    getattr(latest_recommendation, 'created_at', None),
                    getattr(latest_cache, 'updated_at', None) or getattr(latest_cache, 'created_at', None),
                ]
                if value is not None
            ],
            default=None,
        )

        backlog_total = failed_total + open_recommendations + negative_feedback
        health_row = module_health_map.get(module) or {}
        tone = str(health_row.get('tone') or 'calm')
        if backlog_total >= 5 and tone != 'critical':
            tone = 'warning'
        if failed_total or negative_feedback >= 3:
            tone = 'critical'

        if failed_total:
            next_step = 'Problemli AI kayıtlarını açıp prompt ve veri kaynağını birlikte kontrol edin.'
        elif open_recommendations:
            next_step = 'Açık AI önerilerini yönetici kararıyla kapatın ve tekrar edenleri kural haline getirin.'
        elif negative_feedback:
            next_step = 'Olumsuz geri bildirim alan çıktı örneklerini prompt sürümüne göre ayırın.'
        elif report_request_total == 0 and request_total:
            next_step = 'Bu modül için indirilebilir yönetici raporu üretimi henüz zayıf; görünür rapor akışını artırın.'
        else:
            next_step = str(health_row.get('next_step') or 'Operasyon görünümü dengeli; düzenli izleme yeterli.')

        rows.append(
            {
                'module_type': module,
                'tone': tone,
                'risk_score': int(health_row.get('risk_score') or backlog_total),
                'request_total': request_total,
                'visible_request_total': visible_request_total,
                'report_request_total': int(report_request_total or 0),
                'recommendation_total': recommendation_total,
                'open_recommendations': open_recommendations,
                'negative_feedback': negative_feedback,
                'cache_total': cache_total,
                'backlog_total': backlog_total,
                'operational_focus': _feature_focus_text(module, feature_rows),
                'latest_prompt_version': getattr(latest_request, 'prompt_version', None) or '-',
                'latest_activity_at': latest_activity.strftime('%d.%m.%Y %H:%M') if latest_activity else '-',
                'next_step': next_step,
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            -int(item.get('backlog_total') or 0),
            -int(item.get('report_request_total') or 0),
            -int(item.get('request_total') or 0),
            str(item.get('module_type') or ''),
        ),
    )


def _build_center_snapshot(summary: dict[str, int | dict | list], module_health_rows: list[dict[str, int | str]]) -> dict[str, object]:
    provider = get_provider_snapshot()
    using_stub = bool(provider.get("using_stub_mode"))
    ready = bool(provider.get("ready_for_live_provider"))
    provider_label = "Yerel kontrollü AI" if using_stub else ("Gerçek sağlayıcı bağlı" if ready else "Sağlayıcı ayarı eksik")
    live_policy = "Canlı omurga uyumlu" if (using_stub or ready) else "Canlı sağlayıcı bekliyor"
    healthy_count = sum(1 for row in module_health_rows if row.get("tone") == "calm")
    snapshot = dict(provider)
    snapshot.update(
        {
            "provider_label": provider_label,
            "live_policy": live_policy,
            "healthy_count": healthy_count,
            "total_modules": len(module_health_rows),
            "hidden_legacy_request_count": _count_hidden_legacy_requests(),
            "live_table_count": sum(len(ai_module_tables(module)) for module in live_ai_modules(include_system=False)),
        }
    )
    return snapshot


def _build_center_highlights(summary: dict[str, Any], center_snapshot: dict[str, Any]) -> list[dict[str, str]]:
    hidden_count = int(center_snapshot.get("hidden_legacy_request_count") or 0)
    return [
        {
            "title": "Canlı omurga esas alındı",
            "body": "AI görünümü performans, personel/izin, iletişim, anket, geri bildirim, destek ve yönetim panellerine göre süzülür.",
        },
        {
            "title": "Kaldırılan modüller ana vitrine karışmaz",
            "body": f"Canlı kapsam dışı eski modül aileleri gizli tutulur; eski log izi sayısı: {hidden_count}.",
        },
        {
            "title": "Karar değil, kontrollü destek üretir",
            "body": "Özet, önceliklendirme, maskeleme ve öneri kayıt altındadır; nihai idari karar insan onayında kalır.",
        },
    ]


def _build_module_spotlights(module_health_rows: list[dict[str, int | str]]) -> list[dict[str, object]]:
    rows_by_module = {str(row.get("module_type") or ""): row for row in module_health_rows}
    spotlights: list[dict[str, object]] = []
    for module in live_ai_modules(include_system=False):
        row = rows_by_module.get(module, {})
        tone = str(row.get("tone") or "calm")
        open_recommendations = int(row.get("open_recommendations") or 0)
        failed_total = int(row.get("failed_total") or 0)
        negative_feedback = int(row.get("negative_feedback") or 0)
        if failed_total or negative_feedback:
            title = "Öncelikli kontrol gerekiyor"
        elif open_recommendations:
            title = "Yönetici kararı bekleyen öneriler var"
        else:
            title = "Canlı kapsamla uyumlu izleniyor"
        spotlights.append(
            {
                "module_type": module,
                "label": _module_label(module),
                "title": title,
                "body": f"{_module_label(module)} için AI katmanı yalnız canlı omurgadaki tablo ve iş akışlarını esas alır.",
                "focus": _feature_focus_text(module, []),
                "tone": "warning" if tone == "critical" else ("warning" if tone == "warning" else "success"),
                "request_total": int(row.get("request_total") or 0),
                "open_recommendations": open_recommendations,
                "masked_rate": int(row.get("masked_rate") or 0),
                "negative_feedback": negative_feedback,
                "failed_total": failed_total,
                "avg_latency_ms": int(row.get("avg_latency_ms") or 0),
                "next_step": str(row.get("next_step") or "Düzenli izleme yeterli; modül canlı kapsamda tutulur."),
                "href": url_for("main.admin_ai_operations_report", module_type=module),
                "href_label": "Operasyon raporunu aç",
            }
        )
    return spotlights


def _csv_response(filename: str, headers: list[str], rows: list[list[str | int | None]]):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    payload = "\ufeff" + buffer.getvalue()
    response = make_response(payload)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@main_bp.route("/admin/ai-center")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_center():
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        return _render_ai_schema_not_ready(page_title="AI Kontrol Merkezi")
    request_query = _live_request_query()
    recommendation_query = _live_recommendation_query()
    cache_query = _live_cache_query()
    rule_query = _live_rule_query()
    feedback_query = _live_feedback_query()

    request_total = request_query.count()
    recommendation_total = recommendation_query.count()
    open_recommendations = recommendation_query.filter(AIRecommendation.status == "open").count()
    active_rules = rule_query.filter(AIRedactionRule.is_active.is_(True)).count()
    cache_total = cache_query.count()
    failed_requests = request_query.filter(AIRequestLog.status.in_(["failed", "warning"])) .count()
    masked_requests = request_query.filter(AIRequestLog.was_masked.is_(True)).count()
    unmasked_requests = request_query.filter(AIRequestLog.was_masked.is_(False)).count()
    avg_latency_ms = int(request_query.with_entities(func.avg(AIRequestLog.latency_ms)).scalar() or 0)
    prompt_version_total = request_query.with_entities(func.count(func.distinct(AIRequestLog.prompt_version))).scalar() or 0
    feedback_total = feedback_query.count()
    feedback_negative = feedback_query.filter(AIFeedbackLog.feedback_type.in_(["not_helpful", "wrong", "unsafe"])) .count()

    recent_requests = request_query.order_by(AIRequestLog.created_at.desc()).limit(10).all()
    recent_recommendations = recommendation_query.order_by(AIRecommendation.created_at.desc()).limit(10).all()
    recent_rules = rule_query.order_by(AIRedactionRule.updated_at.desc(), AIRedactionRule.created_at.desc()).limit(8).all()
    recent_feedback = (
        feedback_query.order_by(AIFeedbackLog.created_at.desc()).limit(8).all()
    )
    recent_cache = cache_query.order_by(AISummaryCache.updated_at.desc(), AISummaryCache.created_at.desc()).limit(8).all()

    request_status_counts = _status_counts(request_query, AIRequestLog)
    recommendation_status_counts = _status_counts(recommendation_query, AIRecommendation)
    top_modules = _module_counts(request_query, AIRequestLog)
    feedback_types = _top_feedback_types()
    prompt_versions = _prompt_version_counts(request_query)
    module_health_rows = _module_health_rows()

    summary = {
        "request_total": request_total,
        "recommendation_total": recommendation_total,
        "open_recommendations": open_recommendations,
        "active_rules": active_rules,
        "cache_total": cache_total,
        "failed_requests": failed_requests,
        "masked_requests": masked_requests,
        "unmasked_requests": unmasked_requests,
        "masked_rate": _safe_ratio(masked_requests, request_total),
        "avg_latency_ms": avg_latency_ms,
        "prompt_version_total": int(prompt_version_total or 0),
        "feedback_total": feedback_total,
        "feedback_negative": feedback_negative,
        "request_status_counts": request_status_counts,
        "recommendation_status_counts": recommendation_status_counts,
        "top_modules": top_modules,
        "feedback_types": feedback_types,
        "prompt_versions": prompt_versions,
        "module_health_rows": module_health_rows,
        "critical_module_count": sum(1 for row in module_health_rows if row.get("tone") == "critical"),
        "warning_module_count": sum(1 for row in module_health_rows if row.get("tone") == "warning"),
    }
    health_actions = _build_health_actions(summary)
    center_snapshot = _build_center_snapshot(summary, module_health_rows)
    active_module_labels = [_module_label(module) for module in live_ai_modules(include_system=False)]
    center_highlights = _build_center_highlights(summary, center_snapshot)
    module_spotlights = _build_module_spotlights(module_health_rows)

    return safe_render(
        "admin_ai_center.html",
        summary=summary,
        recent_requests=recent_requests,
        recent_recommendations=recent_recommendations,
        recent_rules=recent_rules,
        recent_feedback=recent_feedback,
        recent_cache=recent_cache,
        health_actions=health_actions,
        module_health_rows=module_health_rows[:6],
        center_snapshot=center_snapshot,
        center_highlights=center_highlights,
        module_spotlights=module_spotlights,
        active_module_labels=active_module_labels,
        active_module_count=len(active_module_labels),
        hidden_module_count=len(REMOVED_AI_MODULES),
        now=utc_now(),
    )


@main_bp.route("/admin/ai-requests")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_requests():
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        return _render_ai_schema_not_ready(page_title="AI İşlem Günlükleri")
    base_query = _live_request_query()
    base_query, module_type, feature_type, status, prompt_version, masked_state = _request_filters(base_query)
    page = _safe_int(request.args.get("page"), 1)
    per_page = 40
    pagination = base_query.order_by(AIRequestLog.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    module_options = visible_module_options(distinct_non_empty_values(AIRequestLog.module_type))
    feature_options = distinct_non_empty_values(AIRequestLog.feature_type)
    status_options = distinct_non_empty_values(AIRequestLog.status)
    prompt_version_options = distinct_non_empty_values(AIRequestLog.prompt_version)
    return safe_render(
        "admin_ai_requests.html",
        pagination=pagination,
        rows=pagination.items,
        selected_module_type=module_type,
        selected_feature_type=feature_type,
        selected_status=status,
        selected_prompt_version=prompt_version,
        selected_masked_state=masked_state,
        module_options=module_options,
        feature_options=feature_options,
        status_options=status_options,
        prompt_version_options=prompt_version_options,
    )


@main_bp.route("/admin/ai-requests/export")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_requests_export():
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        flash(schema_status.get("message") or "AI şeması hazır değil.", "warning")
        return redirect(url_for("main.admin_ai_center"))
    base_query = _live_request_query()
    base_query, *_ = _request_filters(base_query)
    rows = base_query.order_by(AIRequestLog.created_at.desc()).all()
    csv_rows: list[list[str | int | None]] = []
    for row in rows:
        csv_rows.append(
            [
                row.created_at.strftime("%d.%m.%Y %H:%M") if row.created_at else None,
                row.module_type,
                row.feature_type,
                row.status,
                row.prompt_version,
                row.provider_name,
                row.model_name,
                "Evet" if row.was_masked else "Hayır",
                "Evet" if row.was_user_visible else "Hayır",
                row.latency_ms,
                row.user.full_name if row.user else None,
                row.target_table,
                row.target_id,
                row.error_message or row.response_text,
            ]
        )
    return _csv_response(
        "bys360_ai_istek_gunlukleri.csv",
        [
            "Zaman",
            "Modul",
            "Ozellik",
            "Durum",
            "Prompt Surumu",
            "Saglayici",
            "Model",
            "Maskelendi",
            "Kullaniciya Gorunur",
            "Gecikme Ms",
            "Kullanici",
            "Hedef Tablo",
            "Hedef ID",
            "Not",
        ],
        csv_rows,
    )


@main_bp.route("/admin/ai-feedback")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_feedback():
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        return _render_ai_schema_not_ready(page_title="AI Geri Bildirimleri")
    base_query = _live_feedback_query()
    base_query, feedback_type, module_type = _feedback_filters(base_query)
    page = _safe_int(request.args.get("page"), 1)
    per_page = 40
    pagination = base_query.order_by(AIFeedbackLog.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    feedback_type_options = distinct_non_empty_values(AIFeedbackLog.feedback_type)
    module_options = visible_module_options(distinct_non_empty_values(AIRequestLog.module_type))
    return safe_render(
        "admin_ai_feedback.html",
        pagination=pagination,
        rows=pagination.items,
        selected_feedback_type=feedback_type,
        selected_module_type=module_type,
        feedback_type_options=feedback_type_options,
        module_options=module_options,
    )


@main_bp.route("/admin/ai-feedback/export")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_feedback_export():
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        flash(schema_status.get("message") or "AI şeması hazır değil.", "warning")
        return redirect(url_for("main.admin_ai_center"))
    base_query = _live_feedback_query()
    base_query, *_ = _feedback_filters(base_query)
    rows = base_query.order_by(AIFeedbackLog.created_at.desc()).all()
    csv_rows: list[list[str | int | None]] = []
    for row in rows:
        request_log = row.ai_request_log
        csv_rows.append(
            [
                row.created_at.strftime("%d.%m.%Y %H:%M") if row.created_at else None,
                row.feedback_type,
                row.feedback_note,
                row.user.full_name if row.user else None,
                request_log.module_type if request_log else None,
                request_log.feature_type if request_log else None,
                request_log.prompt_version if request_log else None,
                request_log.model_name if request_log else None,
                request_log.target_table if request_log else None,
                request_log.target_id if request_log else None,
            ]
        )
    return _csv_response(
        "bys360_ai_geri_bildirimleri.csv",
        [
            "Zaman",
            "Geri Bildirim Tipi",
            "Not",
            "Kullanici",
            "Modul",
            "Ozellik",
            "Prompt Surumu",
            "Model",
            "Hedef Tablo",
            "Hedef ID",
        ],
        csv_rows,
    )

@main_bp.route("/admin/ai-module-health")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_module_health():
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        return _render_ai_schema_not_ready(page_title="AI Modül Sağlığı", selected_module_type=(request.args.get("module_type") or "").strip().lower())
    selected_module_type = _normalize_selected_module(request.args.get("module_type"))
    rows = _module_health_rows(selected_module_type or None)
    module_options = _all_ai_modules()
    summary = {
        "module_count": len(rows),
        "critical_count": sum(1 for row in rows if row.get("tone") == "critical"),
        "warning_count": sum(1 for row in rows if row.get("tone") == "warning"),
        "request_total": sum(int(row.get("request_total") or 0) for row in rows),
        "cache_total": sum(int(row.get("cache_total") or 0) for row in rows),
        "open_recommendations": sum(int(row.get("open_recommendations") or 0) for row in rows),
    }
    return safe_render(
        "admin_ai_module_health.html",
        rows=rows,
        summary=summary,
        module_options=module_options,
        selected_module_type=selected_module_type,
    )


@main_bp.route("/admin/ai-module-health/export")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_module_health_export():
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        flash(schema_status.get("message") or "AI şeması hazır değil.", "warning")
        return redirect(url_for("main.admin_ai_center"))
    selected_module_type = _normalize_selected_module(request.args.get("module_type"))
    rows = _module_health_rows(selected_module_type or None)
    csv_rows: list[list[str | int | None]] = []
    for row in rows:
        csv_rows.append(
            [
                row.get("module_type"),
                row.get("tone"),
                row.get("risk_score"),
                row.get("request_total"),
                row.get("failed_total"),
                row.get("masked_total"),
                row.get("unmasked_total"),
                row.get("masked_rate"),
                row.get("feedback_total"),
                row.get("negative_feedback"),
                row.get("recommendation_total"),
                row.get("open_recommendations"),
                row.get("active_rules"),
                row.get("cache_total"),
                row.get("avg_latency_ms"),
                row.get("latest_prompt_version"),
                row.get("latest_cache_kind"),
                row.get("next_step"),
            ]
        )
    return _csv_response(
        "bys360_ai_modul_sagligi.csv",
        [
            "Modul",
            "Ton",
            "Risk Skoru",
            "AI Istek",
            "Hata/Warning",
            "Maskeli",
            "Maskesiz",
            "Maskeleme Orani",
            "Geri Bildirim",
            "Negatif Geri Bildirim",
            "Oneri Toplami",
            "Acik Oneri",
            "Aktif Kural",
            "Cache",
            "Ortalama Gecikme Ms",
            "Son Prompt",
            "Son Cache",
            "Sonraki Adim",
        ],
        csv_rows,
    )


@main_bp.route("/admin/ai-operations-report")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_operations_report():
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        return _render_ai_schema_not_ready(page_title="AI Operasyon Raporu", selected_module_type=(request.args.get("module_type") or "").strip().lower())
    selected_module_type = _normalize_selected_module(request.args.get("module_type"))
    rows = _operations_report_rows(selected_module_type or None)
    summary = {
        "module_count": len(rows),
        "request_total": sum(int(row.get("request_total") or 0) for row in rows),
        "report_request_total": sum(int(row.get("report_request_total") or 0) for row in rows),
        "open_recommendations": sum(int(row.get("open_recommendations") or 0) for row in rows),
        "negative_feedback": sum(int(row.get("negative_feedback") or 0) for row in rows),
        "backlog_total": sum(int(row.get("backlog_total") or 0) for row in rows),
        "critical_count": sum(1 for row in rows if row.get("tone") == "critical"),
        "warning_count": sum(1 for row in rows if row.get("tone") == "warning"),
    }
    return safe_render(
        "admin_ai_operations_report.html",
        rows=rows,
        summary=summary,
        module_options=_all_ai_modules(),
        selected_module_type=selected_module_type,
    )


@main_bp.route("/admin/ai-operations-report/export")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_operations_report_export():
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        flash(schema_status.get("message") or "AI şeması hazır değil.", "warning")
        return redirect(url_for("main.admin_ai_center"))
    selected_module_type = _normalize_selected_module(request.args.get("module_type"))
    rows = _operations_report_rows(selected_module_type or None)
    csv_rows: list[list[str | int | None]] = []
    for row in rows:
        csv_rows.append(
            [
                row.get("module_type"),
                row.get("tone"),
                row.get("risk_score"),
                row.get("request_total"),
                row.get("visible_request_total"),
                row.get("report_request_total"),
                row.get("recommendation_total"),
                row.get("open_recommendations"),
                row.get("negative_feedback"),
                row.get("cache_total"),
                row.get("backlog_total"),
                row.get("operational_focus"),
                row.get("latest_prompt_version"),
                row.get("latest_activity_at"),
                row.get("next_step"),
            ]
        )
    return _csv_response(
        "bys360_ai_operasyon_raporu.csv",
        [
            "Modul",
            "Ton",
            "Risk Skoru",
            "AI Istek",
            "Gorunur Istek",
            "Rapor/Ozet Istegi",
            "Oneri Toplami",
            "Acik Oneri",
            "Negatif Geri Bildirim",
            "Cache",
            "Operasyon Backlog",
            "Operasyon Odagi",
            "Son Prompt",
            "Son Aktivite",
            "Sonraki Adim",
        ],
        csv_rows,
    )


@main_bp.route("/admin/ai-preflight")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_preflight():
    snapshot = build_ai_preflight_snapshot()
    return safe_render(
        "admin_ai_preflight.html",
        snapshot=snapshot,
        grouped_checks=snapshot.get("grouped_checks") or {},
        summary=snapshot.get("summary") or {},
        schema_status=snapshot.get("schema_status") or {},
        top_actions=snapshot.get("top_actions") or [],
        smoke_paths=snapshot.get("smoke_paths") or [],
    )


@main_bp.route("/admin/ai-preflight/export")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_preflight_export():
    snapshot = build_ai_preflight_snapshot()
    rows = snapshot.get("checks") or []
    csv_rows: list[list[str | int | None]] = []
    for row in rows:
        csv_rows.append(
            [
                row.get("category"),
                row.get("label"),
                row.get("status"),
                row.get("detail"),
                row.get("advice"),
            ]
        )
    return _csv_response(
        "bys360_ai_preflight.csv",
        ["Kategori", "Kontrol", "Durum", "Detay", "Oneri"],
        csv_rows,
    )

@main_bp.route("/admin/ai-smoke")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_smoke():
    snapshot = build_ai_smoke_snapshot()
    return safe_render(
        "admin_ai_smoke.html",
        snapshot=snapshot,
        summary=snapshot.get("summary") or {},
        rows=snapshot.get("rows") or [],
        by_role=snapshot.get("by_role") or {},
        top_notes=snapshot.get("top_notes") or [],
    )


@main_bp.route("/admin/ai-smoke/export")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_smoke_export():
    snapshot = build_ai_smoke_snapshot()
    rows = snapshot.get("rows") or []
    csv_rows: list[list[str | int | None]] = []
    for row in rows:
        csv_rows.append([
            row.get("priority"),
            row.get("role"),
            row.get("label"),
            row.get("path"),
            row.get("goal"),
            row.get("expected"),
            row.get("tone"),
        ])
    return _csv_response(
        "bys360_ai_smoke_kontrol_listesi.csv",
        ["Oncelik", "Rol", "Ekran", "Yol", "Amac", "Beklenen Sonuc", "Ton"],
        csv_rows,
    )


@main_bp.route("/admin/ai-recommendations")
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_recommendations():
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        return _render_ai_schema_not_ready(page_title="AI Öneri Merkezi")
    base_query = _live_recommendation_query()
    base_query, module_type, severity, status = _recommendation_filters(base_query)
    page = _safe_int(request.args.get("page"), 1)
    per_page = 40
    pagination = base_query.order_by(AIRecommendation.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    module_options = visible_module_options(distinct_non_empty_values(AIRecommendation.module_type))
    severity_options = distinct_non_empty_values(AIRecommendation.severity)
    status_options = distinct_non_empty_values(AIRecommendation.status)
    return safe_render(
        "admin_ai_recommendations.html",
        pagination=pagination,
        rows=pagination.items,
        selected_module_type=module_type,
        selected_severity=severity,
        selected_status=status,
        module_options=module_options,
        severity_options=severity_options,
        status_options=status_options,
    )


@main_bp.route("/admin/ai-recommendations/<int:recommendation_id>/status", methods=["POST"])
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_recommendation_status(recommendation_id: int):
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        flash(schema_status.get("message") or "AI şeması hazır değil.", "warning")
        return redirect(url_for("main.admin_ai_center"))
    target_status = (request.form.get("status") or "").strip().lower()
    try:
        mark_recommendation(recommendation_id, status=target_status, reviewed_by_user_id=getattr(current_user, "id", None))
        db.session.commit()
        flash("AI öneri durumu güncellendi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("AI öneri durumu güncellenemedi.", "danger")
    return redirect(request.referrer or url_for("main.admin_ai_recommendations"))


@main_bp.route("/admin/ai-redaction-rules", methods=["GET", "POST"])
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_redaction_rules():
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        return _render_ai_schema_not_ready(page_title="AI Maskeleme Kuralları")
    if request.method == "POST":
        module_type = _normalize_selected_module(request.form.get("module_type"))
        field_name = (request.form.get("field_name") or "").strip()
        redaction_type = (request.form.get("redaction_type") or "").strip().lower()
        replacement_text = (request.form.get("replacement_text") or "").strip() or None
        if not module_type or not field_name or not redaction_type:
            flash("Modül, alan ve redaction tipi zorunludur.", "danger")
        else:
            try:
                row = AIRedactionRule.query.filter_by(module_type=module_type, field_name=field_name).first()
                if row is None:
                    row = AIRedactionRule(
                        module_type=module_type,
                        field_name=field_name,
                        created_by_id=getattr(current_user, "id", None),
                    )
                row.redaction_type = redaction_type
                row.replacement_text = replacement_text
                row.is_active = True
                row.updated_by_id = getattr(current_user, "id", None)
                db.session.add(row)
                db.session.commit()
                flash("AI maskeleme kuralı kaydedildi.", "success")
                return redirect(url_for("main.admin_ai_redaction_rules"))
            except Exception as exc:
                logger.exception("Beklenmeyen hata: %s", exc)
                db.session.rollback()
                flash("AI maskeleme kuralı kaydedilemedi.", "danger")

    redaction_query = _live_rule_query()
    rows = redaction_query.order_by(AIRedactionRule.module_type.asc(), AIRedactionRule.field_name.asc()).all()
    active_count = redaction_query.filter(AIRedactionRule.is_active.is_(True)).count()
    choices = _redaction_choices()
    return safe_render(
        "admin_ai_redaction_rules.html",
        rows=rows,
        active_count=active_count,
        module_options=choices["modules"],
        field_name_options=choices["field_names"],
    )


@main_bp.route("/admin/ai-redaction-rules/<int:rule_id>/toggle", methods=["POST"])
@login_required
@admin_required
@menu_key_required("ai_center")
def admin_ai_redaction_toggle(rule_id: int):
    schema_status = get_ai_schema_status()
    if not schema_status.get("ready"):
        flash(schema_status.get("message") or "AI şeması hazır değil.", "warning")
        return redirect(url_for("main.admin_ai_center"))
    row = db.session.get(AIRedactionRule, rule_id)
    if row is None:
        flash("AI maskeleme kuralı bulunamadı.", "danger")
        return redirect(url_for("main.admin_ai_redaction_rules"))
    try:
        row.is_active = not bool(row.is_active)
        row.updated_by_id = getattr(current_user, "id", None)
        db.session.add(row)
        db.session.commit()
        flash("AI maskeleme kuralı durumu güncellendi.", "success")
    except Exception as exc:
        logger.exception("Beklenmeyen hata: %s", exc)
        db.session.rollback()
        flash("AI maskeleme kuralı güncellenemedi.", "danger")
    return redirect(url_for("main.admin_ai_redaction_rules"))
