from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from app.extensions import db

from .dashboard_kpi_bridge import build_dashboard_kpi_summary_for_user
from .performance_bridge import build_performance_summary_for_user
from .repository import table_columns, table_exists


@dataclass(frozen=True)
class ActionTemplate:
    key: str
    title: str
    description: str
    route: str
    category: str
    priority: str = "normal"


ACTION_TEMPLATES: tuple[ActionTemplate, ...] = (
    ActionTemplate(
        key="review_president_approval_queue",
        title="Başkan/Üst Onay bekleyen kayıtları incele",
        description="Düşük performans nedeniyle üst onay bekleyen kayıtları yalnızca ilgili inceleme ekranına yönlendirir.",
        route="/performance/president-approvals",
        category="performans",
        priority="yüksek",
    ),
    ActionTemplate(
        key="review_publish_locks",
        title="Yayın kilidindeki karneleri kontrol et",
        description="Yayın öncesi kilitli görünen karneleri kontrol listesine alır; yayın işlemi yapmaz.",
        route="/performance/process-tracking",
        category="performans",
        priority="yüksek",
    ),
    ActionTemplate(
        key="prepare_delayed_supervisor_followup",
        title="Aksatan amir takibi hazırla",
        description="Geciken değerlendirme görevleri için takip ekranına yönlendirir; bildirim göndermez.",
        route="/performance/meeting-development/faz9",
        category="performans",
        priority="orta",
    ),
    ActionTemplate(
        key="review_risky_kpi_targets",
        title="Riskli KPI/hedefleri incele",
        description="Riskli veya geciken hedefleri stratejik performans analiz ekranına yönlendirir; hedef değeri değiştirmez.",
        route="/performans/stratejik/kpi-analiz",
        category="kpi_hedef",
        priority="yüksek",
    ),
    ActionTemplate(
        key="open_executive_briefing",
        title="Yönetici brifingini aç",
        description="Performans ve KPI özetlerini tek panelde görüntülemeye yönlendirir.",
        route="/ai-agent/panel",
        category="brifing",
        priority="normal",
    ),
)

_TEMPLATE_BY_KEY = {item.key: item for item in ACTION_TEMPLATES}


def _user_id(user: Any) -> int | None:
    try:
        return int(getattr(user, "id", None) or 0) or None
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return None


def _extract_counts(summary: dict[str, Any]) -> dict[str, int]:
    if not isinstance(summary, dict):
        return {}
    counts = raw_counts if isinstance(raw_counts := summary.get("counts"), dict) else summary
    safe: dict[str, int] = {}
    for key, value in counts.items():
        try:
            safe[str(key)] = int(value or 0)
        except Exception:
            safe[str(key)] = 0
    return safe


def _queued_count(user_id: int | None, status: str | None = None) -> int:
    if not table_exists("ai_agent_action_queue"):
        return 0
    columns = table_columns("ai_agent_action_queue")
    where_parts: list[str] = []
    params: dict[str, Any] = {}
    if user_id and "requested_by_user_id" in columns:
        where_parts.append("requested_by_user_id = :user_id")
        params["user_id"] = user_id
    if status and "status" in columns:
        where_parts.append("status = :status")
        params["status"] = status
    where_clause = " WHERE " + " AND ".join(where_parts) if where_parts else ""
    try:
        return int(db.session.execute(text(f"SELECT COUNT(*) FROM ai_agent_action_queue{where_clause}"), params).scalar() or 0)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return 0


def _template_payload(item: ActionTemplate, reason: str | None = None, count: int | None = None) -> dict[str, Any]:
    return {
        "key": item.key,
        "title": item.title,
        "description": item.description,
        "route": item.route,
        "category": item.category,
        "priority": item.priority,
        "reason": reason or item.description,
        "count": int(count or 0),
        "requires_confirmation": True,
        "execution_enabled": False,
        "safety_notice": "Bu öneri yalnızca kuyruğa alınır; iş süreci işlemi kullanıcı tarafından ilgili ekranda yapılır.",
    }


def build_suggested_action_cards_for_user(user: Any) -> list[dict[str, Any]]:
    """Performans/KPI özetlerinden güvenli öneri kartları üretir.

    Bu fonksiyon iş verisi değiştirmez. Yalnızca sayısal özetlere göre öneri kartı hazırlar.
    """
    performance_summary = build_performance_summary_for_user(user)
    kpi_summary = build_dashboard_kpi_summary_for_user(user)
    perf_counts = _extract_counts(performance_summary)
    kpi_counts = _extract_counts(kpi_summary)

    cards: list[dict[str, Any]] = []
    president_count = perf_counts.get("president_approval_waiting", 0) or perf_counts.get("president_approval_pending", 0)
    if president_count:
        cards.append(_template_payload(_TEMPLATE_BY_KEY["review_president_approval_queue"], "Üst onay bekleyen düşük performans kayıtları var.", president_count))

    publish_lock_count = perf_counts.get("publish_locked_scorecards", 0) or perf_counts.get("publish_locked", 0)
    if publish_lock_count:
        cards.append(_template_payload(_TEMPLATE_BY_KEY["review_publish_locks"], "Yayın kilidi kapsamında kontrol bekleyen karne var.", publish_lock_count))

    delayed_count = perf_counts.get("delayed_assignments", 0) or perf_counts.get("delayed_performance_tasks", 0)
    if delayed_count:
        cards.append(_template_payload(_TEMPLATE_BY_KEY["prepare_delayed_supervisor_followup"], "Süresi geçen değerlendirme görevi var.", delayed_count))

    risky_kpi_count = kpi_counts.get("risky_targets", 0) or kpi_counts.get("high_risk_targets", 0)
    if risky_kpi_count:
        cards.append(_template_payload(_TEMPLATE_BY_KEY["review_risky_kpi_targets"], "Riskli veya takip gerektiren hedefler var.", risky_kpi_count))

    if not cards:
        cards.append(_template_payload(_TEMPLATE_BY_KEY["open_executive_briefing"], "Genel yönetici brifingi için güvenli özet paneli açılabilir.", 0))

    return cards[:6]


def build_action_queue_summary_for_user(user: Any) -> dict[str, Any]:
    user_id = _user_id(user)
    return {
        "ok": True,
        "version": "AG-5 V1",
        "mode": "onaylı_aksiyon_kuyrugu",
        "suggested_actions": build_suggested_action_cards_for_user(user),
        "queue_counts": {
            "total": _queued_count(user_id),
            "waiting_confirmation": _queued_count(user_id, "onay_bekliyor"),
            "dismissed": _queued_count(user_id, "kapatildi"),
        },
        "safety": {
            "requires_confirmation": True,
            "execution_enabled": False,
            "notice": "AG-5 önerileri yalnızca kuyruk kaydıdır; gerçek işlem ilgili modül ekranında kullanıcı tarafından yapılır.",
        },
    }


def create_controlled_action_queue_suggestion(user: Any, action_key: str, source: str = "assistant_panel") -> dict[str, Any]:
    """Kullanıcı isteğiyle güvenli öneriyi kuyruğa alır.

    Bu kayıt bir iş süreci işlemi değildir; yalnızca takip ve hatırlatma kaydıdır.
    """
    template = _TEMPLATE_BY_KEY.get(str(action_key or ""))
    if not template:
        return {"ok": False, "error": "Bilinmeyen öneri anahtarı.", "status": "rejected"}

    if not table_exists("ai_agent_action_queue"):
        return {"ok": False, "error": "Aksiyon kuyruğu tablosu bulunamadı.", "status": "schema_pending"}

    user_id = _user_id(user)
    try:
        result = db.session.execute(
            text("""
                INSERT INTO ai_agent_action_queue
                    (requested_by_user_id, action_key, title, description, target_route, category, priority, status, source, requires_confirmation, execution_enabled, created_at, updated_at)
                VALUES
                    (:user_id, :action_key, :title, :description, :target_route, :category, :priority, 'onay_bekliyor', :source, TRUE, FALSE, NOW(), NOW())
                RETURNING id
            """),
            {
                "user_id": user_id,
                "action_key": template.key,
                "title": template.title,
                "description": template.description,
                "target_route": template.route,
                "category": template.category,
                "priority": template.priority,
                "source": source[:80],
            },
        )
        queue_id = int(result.scalar() or 0) or None
        db.session.commit()
    except Exception:
        db.session.rollback()
        # Raw exception text (SQL, table names) must not reach the API client.
        __import__("logging").getLogger(__name__).exception("BYS360 AG-5 aksiyon kuyruğu kaydı oluşturulamadı.")
        return {"ok": False, "error": "Öneri kuyruğa alınamadı. Lütfen daha sonra tekrar deneyin.", "status": "failed"}

    return {
        "ok": True,
        "id": queue_id,
        "status": "onay_bekliyor",
        "message": "Öneri güvenli aksiyon kuyruğuna alındı. Gerçek işlem ilgili ekranda kullanıcı onayıyla yapılmalıdır.",
        "action": _template_payload(template),
    }
