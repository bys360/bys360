from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .action_queue_bridge import (
    build_action_queue_summary_for_user,
    build_suggested_action_cards_for_user,
    create_controlled_action_queue_suggestion,
)
from .assistant_panel_bridge import build_assistant_widget_summary_for_user
from .dashboard_kpi_bridge import build_dashboard_kpi_summary_for_user
from .performance_bridge import build_performance_summary_for_user
from .policy import (
    AG5_CAPABILITIES,
    AI_AGENT_ACTION_QUEUE_NOTICE,
    AI_AGENT_AG6_VERSION,
    AI_AGENT_ASSISTANT_PANEL_NOTICE,
    AI_AGENT_DASHBOARD_KPI_NOTICE,
    AI_AGENT_DECISION_NOTICE,
    AI_AGENT_MODE_LABEL,
    AI_AGENT_NO_AUTOMATION_NOTICE,
    AI_AGENT_PERFORMANCE_NOTICE,
    AI_AGENT_SECURITY_NOTICE,
    capability_payload,
    redact_sensitive_text,
)
from .repository import collect_safe_counts_for_user, insert_agent_request_log, table_exists
from .security_bridge import (
    build_ai_agent_security_policy_payload,
    build_ai_agent_security_self_check as build_ai_agent_security_self_check_payload,
)

# BYS360_ASSISTANT_VISIBLE_TUTOR_V6_IMPORT
bys360_visible_tutor_v6_answer: Callable[..., str] | None
BYS360_VISIBLE_TUTOR_V6_WELCOME: str | None
try:
    from app.services.ai_agent.assistant_visible_tutor_v6 import (
        WELCOME_TEXT as BYS360_VISIBLE_TUTOR_V6_WELCOME,
        answer_visible_tutor_v6 as bys360_visible_tutor_v6_answer,
    )
except Exception:  # pragma: no cover
    bys360_visible_tutor_v6_answer = None
    BYS360_VISIBLE_TUTOR_V6_WELCOME = None
# BYS360_ASSISTANT_VISIBLE_TUTOR_V6_IMPORT_END


def _user_id(user: Any) -> int | None:
    try:
        return int(getattr(user, "id", None) or 0) or None
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return None


def _display_name(user: Any) -> str:
    for attr in ("full_name", "name", "ad_soyad", "email", "username"):
        value = getattr(user, attr, None)
        if value:
            return str(value)
    return "BYS360 kullanıcısı"


def _detect_intent(question: str) -> str:
    text_value = (question or "").lower()
    if any(word in text_value for word in ("brifing", "briefing", "başkan özeti", "baskan ozeti", "yönetici özeti", "yonetici ozeti", "bugünkü özet", "bugunku ozet")):
        return "executive_briefing"
    if any(word in text_value for word in ("kpi", "hedef", "stratejik", "gerçekleşme", "gerceklesme", "riskli hedef")):
        return "strategic_kpi"
    if any(word in text_value for word in ("başkan", "baskan", "onay", "70", "düşük", "dusuk")):
        return "president_approval"
    if any(word in text_value for word in ("yayın", "yayin", "kilit", "karne")):
        return "publish_lock"
    if any(word in text_value for word in ("aksatan", "geciken", "gecikti", "amir", "bekleyen görev", "bekleyen gorev")):
        return "delayed_supervisors"
    if any(word in text_value for word in ("performans", "puan", "dönem", "donem", "değerlendirme", "degerlendirme")):
        return "performance_status"
    if any(word in text_value for word in ("destek", "talep", "yardım", "yardim")):
        return "support_triage"
    if any(word in text_value for word in ("yetki", "ayar", "menü", "menu", "rol")):
        return "settings_visibility"
    if any(word in text_value for word in ("aksiyon", "öneri", "onay kuyruğu", "onayli aksiyon", "kuyruğa al", "kuyruga al", "takip listesi")):
        return "action_queue"
    if any(word in text_value for word in ("güvenlik", "guvenlik", "yetki kaçağı", "yetki kacagi", "hassas veri", "public", "endpoint", "kaçak test", "kacak test")):
        return "security_gate"
    if any(word in text_value for word in ("asistan", "panel", "sağ alt", "sag alt")):
        return "assistant_panel"
    return "general_guidance"


def _intent_answer(
    intent: str,
    counts: dict[str, int],
    performance_summary: dict[str, Any],
    dashboard_kpi_summary: dict[str, Any],
) -> str:
    perf_counts = performance_summary.get("counts", {}) if isinstance(performance_summary, dict) else {}
    kpi_counts = dashboard_kpi_summary.get("counts", {}) if isinstance(dashboard_kpi_summary, dict) else {}
    if intent == "action_queue":
        return (
            "AG-5 onaylı aksiyon kuyruğu aktiftir. BYS360 Asistanı yalnızca güvenli öneri kartları oluşturur ve önerileri takip kuyruğuna alır. "
            "Gerçek iş süreci işlemleri ilgili modül ekranında kullanıcı tarafından ayrıca yapılmalıdır."
        )
    if intent == "security_gate":
        return (
            "AG-6 canlı güvenlik kapısı aktiftir. BYS360 Asistanı endpointleri login zorunluluğu, hassas veri sınırı, public health güvenliği ve "
            "otomatik işlem kapalı ayarlarıyla denetlenir. Güvenlik kontrolü veri değiştirmez; yalnızca rapor ve uyarı üretir."
        )
    if intent == "assistant_panel":
        return (
            "AG-5 BYS360 Asistanı paneli aktiftir. Sağ alt panel performans, KPI/Hedef ve destek özetlerini güvenli kartlarla gösterir. "
            "Panel hassas içerik göstermez ve idari karar üretmez."
        )
    if intent == "executive_briefing":
        notes = dashboard_kpi_summary.get("briefing_notes") or []
        first_note = notes[0] if notes else "KPI/Hedef brifingi güvenli özet düzeyinde hazırlandı."
        return (
            f"Yönetici brifingi güvenli özet olarak hazırlandı. {first_note} "
            f"Performans tarafında {perf_counts.get('pending_assignments', counts.get('pending_performance_assignments', 0))} bekleyen değerlendirme, "
            f"KPI tarafında {kpi_counts.get('risky_targets', 0)} riskli hedef görünüyor. "
            "BYS360 Asistanı yalnızca brifing ve yönlendirme üretir; idari karar veya veri değişikliği yapmaz."
        )
    if intent == "strategic_kpi":
        return (
            f"KPI/Hedef bağlantısı için AG-5 güvenli özet üretildi. "
            f"Yetki kapsamına göre {kpi_counts.get('total_targets', 0)} hedef, "
            f"%{kpi_counts.get('average_completion', 0)} ortalama gerçekleşme ve "
            f"{kpi_counts.get('risky_targets', 0)} riskli hedef görünüyor. "
            "BYS360 Asistanı hedef kapatmaz, hedef değeri değiştirmez; ilgili dashboard ve analiz ekranına yönlendirir."
        )
    if intent == "president_approval":
        return (
            f"Başkan/Üst Onay odağında güvenli özet hazırlandı. "
            f"Yetki kapsamına göre {perf_counts.get('president_approval_waiting', counts.get('president_approval_waiting', 0))} onay bekleyen düşük performans kaydı görünüyor. "
            "BYS360 Asistanı yalnızca yönlendirme yapar; onay veya ret işlemi gerçekleştirmez."
        )
    if intent == "publish_lock":
        return (
            f"Yayın kilidi odağında güvenli özet hazırlandı. "
            f"Yetki kapsamına göre {perf_counts.get('publish_locked_scorecards', counts.get('publish_locked_scorecards', 0))} karne yayın kilidi kapsamında görünüyor. "
            "BYS360 Asistanı karneyi yayıma açmaz; ilgili kontrol ekranına yönlendirir."
        )
    if intent == "delayed_supervisors":
        return (
            f"Geciken değerlendirme görevleri için güvenli sayı özeti üretildi. "
            f"Yetki kapsamına göre {perf_counts.get('delayed_assignments', counts.get('delayed_performance_tasks', 0))} geciken görev görünüyor. "
            "Kişi detayı yalnızca yetkili performans ekranında görüntülenmelidir."
        )
    if intent == "performance_status":
        return (
            f"Performans süreci için AG-5 güvenli durum özeti üretildi. "
            f"Yetki kapsamına göre {perf_counts.get('pending_assignments', counts.get('pending_performance_assignments', 0))} bekleyen değerlendirme görevi görünüyor. "
            "Detaylar yalnızca kullanıcının yetkili olduğu ekranlarda görüntülenmelidir."
        )
    if intent == "support_triage":
        return (
            f"Destek ve talep tarafında güvenli sayı özeti hazırlandı. "
            f"Size bağlı açık destek talebi sayısı: {counts.get('open_support_tickets', 0)}. "
            "Talep içerikleri doğrudan dökülmez; ilgili destek ekranına yönlendirme yapılır."
        )
    if intent == "settings_visibility":
        return (
            "Yetki, rol ve menü görünürlüğü için Sistem Ayarları ekranı esas alınmalıdır. "
            "BYS360 Asistanı yetki vermez veya kaldırmaz; sadece doğru ayar alanına yönlendirir."
        )
    return (
        "BYS360 Asistanı hazır. BYS360 ekranlarında işlem adımlarını sade şekilde açıklar, doğru sayfaya yönlendirir ve yetkiniz dahilinde güvenli özet sunar. "
        "Onayınız olmadan işlem yapılmaz; yetki dışı veri gösterilmez."
    )


def build_ai_agent_health_payload() -> dict[str, Any]:
    required_tables = (
        "ai_agent_settings",
        "ai_agent_request_logs",
        "ai_agent_task_suggestions",
        "ai_agent_action_audit_logs",
        "ai_agent_widget_events",
        "ai_agent_action_queue",
        "ai_agent_security_gate_logs",
    )
    performance_tables = (
        "performance_periods",
        "evaluation_assignments",
        "performance_evaluations",
    )
    kpi_target_tables = (
        "performance_targets",
        "strategic_targets",
        "kpi_targets",
        "target_cards",
        "sp1_target_cards",
        "sp1_targets",
    )
    table_status = {name: table_exists(name) for name in required_tables}
    performance_status = {name: table_exists(name) for name in performance_tables}
    kpi_status = {name: table_exists(name) for name in kpi_target_tables}
    return {
        "status": "ok" if all(table_status.values()) else "schema_pending",
        "service": "bys360-ai-agent",
        "version": AI_AGENT_AG6_VERSION,
        "mode": AI_AGENT_MODE_LABEL,
        "decision_notice": AI_AGENT_DECISION_NOTICE,
        "automation_notice": AI_AGENT_NO_AUTOMATION_NOTICE,
        "security_notice": AI_AGENT_SECURITY_NOTICE,
        "performance_notice": AI_AGENT_PERFORMANCE_NOTICE,
        "dashboard_kpi_notice": AI_AGENT_DASHBOARD_KPI_NOTICE,
        "assistant_panel_notice": AI_AGENT_ASSISTANT_PANEL_NOTICE,
        "ag2_performance_bridge": True,
        "ag3_dashboard_kpi_bridge": True,
        "ag4_assistant_panel_bridge": True,
        "ag5_action_queue_bridge": True,
        "ag6_security_gate": True,
        "tables": table_status,
        "performance_tables": performance_status,
        "kpi_target_tables": kpi_status,
    }


def build_ai_agent_action_cards(user: Any) -> list[dict[str, str]]:
    return [
        {
            "key": capability.key,
            "title": capability.title,
            "description": capability.description,
            "route": capability.route,
            "safety_level": capability.safety_level,
        }
        for capability in AG5_CAPABILITIES
    ]


def build_ai_agent_performance_summary(user: Any) -> dict[str, Any]:
    return build_performance_summary_for_user(user)


def build_ai_agent_dashboard_kpi_summary(user: Any) -> dict[str, Any]:
    return build_dashboard_kpi_summary_for_user(user)


def build_ai_agent_assistant_widget_summary(user: Any) -> dict[str, Any]:
    return build_assistant_widget_summary_for_user(user)


def build_ai_agent_action_queue_summary(user: Any) -> dict[str, Any]:
    return build_action_queue_summary_for_user(user)


def build_ai_agent_security_policy(user: Any) -> dict[str, Any]:
    return build_ai_agent_security_policy_payload(user)


def build_ai_agent_security_self_check(user: Any) -> dict[str, Any]:
    return build_ai_agent_security_self_check_payload(user)


def enqueue_ai_agent_suggestion(user: Any, action_key: str, source: str = "assistant_panel") -> dict[str, Any]:
    return create_controlled_action_queue_suggestion(user, action_key, source=source)


def build_ai_agent_panel_context(user: Any) -> dict[str, Any]:
    user_id = _user_id(user)
    counts = collect_safe_counts_for_user(user_id)
    performance_summary = build_ai_agent_performance_summary(user)
    dashboard_kpi_summary = build_ai_agent_dashboard_kpi_summary(user)
    assistant_widget_summary = build_ai_agent_assistant_widget_summary(user)
    action_queue_summary = build_ai_agent_action_queue_summary(user)
    return {
        "version": AI_AGENT_AG6_VERSION,
        "mode": AI_AGENT_MODE_LABEL,
        "display_name": _display_name(user),
        "counts": counts,
        "performance_summary": performance_summary,
        "dashboard_kpi_summary": dashboard_kpi_summary,
        "assistant_widget_summary": assistant_widget_summary,
        "action_queue_summary": action_queue_summary,
        "suggested_actions": build_suggested_action_cards_for_user(user),
        "capabilities": capability_payload(),
        "decision_notice": AI_AGENT_DECISION_NOTICE,
        "automation_notice": AI_AGENT_NO_AUTOMATION_NOTICE,
        "security_notice": AI_AGENT_SECURITY_NOTICE,
        "performance_notice": AI_AGENT_PERFORMANCE_NOTICE,
        "dashboard_kpi_notice": AI_AGENT_DASHBOARD_KPI_NOTICE,
        "assistant_panel_notice": AI_AGENT_ASSISTANT_PANEL_NOTICE,
        "action_queue_notice": AI_AGENT_ACTION_QUEUE_NOTICE,
    }


def _legacy_build_ai_agent_reply_v0(user: Any, question: str) -> dict[str, Any]:
    safe_question = redact_sensitive_text(question)
    intent = _detect_intent(safe_question)
    counts = collect_safe_counts_for_user(_user_id(user))
    performance_summary = build_ai_agent_performance_summary(user)
    dashboard_kpi_summary = build_ai_agent_dashboard_kpi_summary(user)
    assistant_widget_summary = build_ai_agent_assistant_widget_summary(user)
    action_queue_summary = build_ai_agent_action_queue_summary(user)
    answer = _intent_answer(intent, counts, performance_summary, dashboard_kpi_summary)
    action_cards = build_ai_agent_action_cards(user)
    log_id = insert_agent_request_log(
        user_id=_user_id(user),
        prompt=safe_question,
        intent=intent,
        response_summary=answer,
    )
    return {
        "ok": True,
        "version": AI_AGENT_AG6_VERSION,
        "mode": AI_AGENT_MODE_LABEL,
        "intent": intent,
        "answer": answer,
        "counts": counts,
        "performance_summary": performance_summary,
        "dashboard_kpi_summary": dashboard_kpi_summary,
        "assistant_widget_summary": assistant_widget_summary,
        "action_queue_summary": action_queue_summary,
        "suggested_actions": build_suggested_action_cards_for_user(user),
        "actions": action_cards,
        "log_id": log_id,
        "notice": AI_AGENT_DECISION_NOTICE,
        "automation_notice": AI_AGENT_NO_AUTOMATION_NOTICE,
        "security_notice": AI_AGENT_SECURITY_NOTICE,
        "performance_notice": AI_AGENT_PERFORMANCE_NOTICE,
        "dashboard_kpi_notice": AI_AGENT_DASHBOARD_KPI_NOTICE,
        "assistant_panel_notice": AI_AGENT_ASSISTANT_PANEL_NOTICE,
        "action_queue_notice": AI_AGENT_ACTION_QUEUE_NOTICE,
    }

# BYS360_AG3_ASSISTANT_CONVERSATION_RUNTIME_START
def _ag3_lower(value: Any) -> str:
    return str(value or "").lower().replace("ı", "i").replace("İ", "i")


def _ag3_action(label: str, route: str, description: str = "") -> dict[str, str]:
    return {
        "title": label,
        "label": label,
        "route": route,
        "url": route,
        "description": description,
        "safety_level": "rehber_yonlendirme",
    }


def _ag3_detect_intent(question: str) -> str:
    q = _ag3_lower(question)
    if any(x in q for x in ("karne", "karnem", "puanım", "puanim", "sonucum", "sonuç", "geçmiş karne", "gecmis karne")):
        return "my_scorecard"
    if any(x in q for x in ("başkan onay", "baskan onay", "70 alti", "70 altı", "düşük performans", "dusuk performans")):
        return "president_approval"
    if any(x in q for x in ("bekleyen görev", "bekleyen gorev", "görevlerim", "gorevlerim", "değerlendirme görev", "degerlendirme gorev")):
        return "my_tasks"
    if any(x in q for x in ("anket", "anketlerim", "geri bildirim", "nabiz", "nabız")):
        return "survey_feedback"
    if any(x in q for x in ("destek", "talep", "yardim", "yardım", "arıza", "ariza")):
        return "support"
    if any(x in q for x in ("duyuru", "bildirim", "mesaj", "okunmamis", "okunmamış")):
        return "communication"
    if any(x in q for x in ("kpi", "hedef", "stratejik", "riskli hedef", "gerçekleşme", "gerceklesme")):
        return "kpi_targets"
    if any(x in q for x in ("yetki", "rol", "menu", "menü", "ayar", "görünmüyor", "gorunmuyor")):
        return "settings"
    if any(x in q for x in ("asistan", "soru", "nasil", "nasıl", "ne yapabilirsin", "yardimci")):
        return "assistant_help"
    return _detect_intent(question)


def _ag3_answer_and_actions(intent: str, counts: dict[str, Any], performance_summary: dict[str, Any], dashboard_kpi_summary: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    perf_counts = performance_summary.get("counts", {}) if isinstance(performance_summary, dict) else {}
    kpi_counts = dashboard_kpi_summary.get("counts", {}) if isinstance(dashboard_kpi_summary, dict) else {}

    if intent == "my_scorecard":
        return (
            "Karnenizi yalnızca yayın/onay süreci tamamlandıktan sonra görebilirsiniz. Kendi karne ekranınızda yayınlanmış sonuç, açıklama ve varsa geçmiş karne bağlantıları yer alır. Asistan puan veya amir görüşü göstermez; ilgili güvenli ekrana yönlendirir.",
            [_ag3_action("Karneme git", "/performance/scorecard"), _ag3_action("Geçmiş karneler", "/performance/archive")]
        )

    if intent == "president_approval":
        count = perf_counts.get("president_approval_waiting", counts.get("president_approval_waiting", 0))
        return (
            f"Yetki kapsamınıza göre Başkan/Üst Onay bekleyen düşük performans kayıt sayısı: {count}. Bu süreçte asistan onay veya ret işlemi yapmaz; yalnızca ilgili kontrol ekranına yönlendirir.",
            [_ag3_action("Başkan Onayları", "/performance/president-approvals"), _ag3_action("Süreç Takibi", "/performance/process-tracking")]
        )

    if intent == "my_tasks":
        count = perf_counts.get("pending_assignments", counts.get("pending_performance_assignments", 0))
        return (
            f"Yetki kapsamınıza göre bekleyen performans/değerlendirme görevi sayısı: {count}. Görev detayları ve işlem adımları yalnızca ilgili performans ekranında görülmelidir.",
            [_ag3_action("Performans görevlerim", "/performance/tasks"), _ag3_action("Performans paneli", "/performance/dashboard")]
        )

    if intent == "survey_feedback":
        return (
            "Anket ve geri bildirimlerde asistan cevap içeriği göstermez. Size açık anketleri, geri bildirim veya nabız ekranlarını güvenli şekilde bulmanıza yardımcı olur.",
            [_ag3_action("Anketler", "/surveys"), _ag3_action("Geri bildirim", "/communication/feedback"), _ag3_action("Bildirimler", "/notifications")]
        )

    if intent == "support":
        open_count = counts.get("open_support_tickets", 0)
        return (
            f"Açık destek talebi sayısı güvenli özet düzeyinde: {open_count}. Asistan talep içeriğini dökmez; yeni talep oluşturma veya destek ekranına yönlendirme yapar.",
            [_ag3_action("Destek talebi oluştur", "/support/new"), _ag3_action("Destek taleplerim", "/support")]
        )

    if intent == "communication":
        return (
            "Duyuru, bildirim ve mesajlarda asistan içerik dökmez; yalnızca ilgili ekranlara güvenli yönlendirme yapar. Okunmamış içerikler yetki ve kullanıcı kapsamına göre ilgili modülde görüntülenir.",
            [_ag3_action("Bildirimler", "/notifications"), _ag3_action("Duyurular", "/announcements"), _ag3_action("Mesajlar", "/messages")]
        )

    if intent == "kpi_targets":
        risky = kpi_counts.get("risky_targets", counts.get("risky_targets", 0))
        total = kpi_counts.get("total_targets", counts.get("total_targets", 0))
        return (
            f"KPI/Hedef tarafında yetki kapsamınıza göre toplam hedef: {total}, riskli hedef: {risky}. Asistan hedef kapatmaz veya değer değiştirmez; yalnızca analiz ekranına yönlendirir.",
            [_ag3_action("KPI/Hedef paneli", "/performans/stratejik/kpi-dashboard"), _ag3_action("KPI analiz", "/performans/stratejik/kpi-analiz")]
        )

    if intent == "settings":
        return (
            "Rol, menü ve modül görünürlüğü Sistem Ayarları üzerinden yönetilmelidir. Asistan yetki vermez veya kaldırmaz; yalnızca doğru ayar alanına yönlendirir.",
            [_ag3_action("Rol Matrisi", "/admin/role-matrix"), _ag3_action("Sistem Ayarları", "/settings")]
        )

    if intent == "assistant_help":
        return (
            "BYS360 Asistanı; Personel Yönetimi, Performans Yönetimi, İletişim/Anket/Destek, Sistem Ayarları, KPI/Hedef ve kullanıcı işlemlerinde adım adım kullanım rehberi sağlar. Cevaplarım rehberlik ve güvenli yönlendirme içindir; idari karar üretmem, performans puanı üzerinde yetkisiz işlem yapmem ve yetki dışı veri göstermem.",
            [_ag3_action("Performans görevlerim", "/performance/tasks"), _ag3_action("Destek", "/support"), _ag3_action("Bildirimler", "/notifications")]
        )

    answer = _intent_answer(intent, counts, performance_summary, dashboard_kpi_summary)
    return answer, build_ai_agent_action_cards(None)


def _legacy_build_ai_agent_reply_ag3(user: Any, question: str) -> dict[str, Any]:
    safe_question = redact_sensitive_text(question or "")
    if not safe_question.strip():
        return {
            "ok": False,
            "answer": "Lütfen BYS360 içinde yapmak istediğiniz işlemi kısa bir cümleyle yazın.",
            "actions": [_ag3_action("Yardım Merkezi", "/support")],
            "notice": AI_AGENT_DECISION_NOTICE,
        }

    intent = _ag3_detect_intent(safe_question)
    counts = collect_safe_counts_for_user(_user_id(user))
    performance_summary = build_ai_agent_performance_summary(user)
    dashboard_kpi_summary = build_ai_agent_dashboard_kpi_summary(user)
    assistant_widget_summary = build_ai_agent_assistant_widget_summary(user)
    action_queue_summary = build_ai_agent_action_queue_summary(user)
    answer, actions = _ag3_answer_and_actions(intent, counts, performance_summary, dashboard_kpi_summary)

    log_id = insert_agent_request_log(
        user_id=_user_id(user),
        prompt=safe_question,
        intent=intent,
        response_summary=answer,
    )

    return {
        "ok": True,
        "version": "AG-3 Soru-Cevap V1",
        "mode": AI_AGENT_MODE_LABEL,
        "intent": intent,
        "answer": answer,
        "counts": counts,
        "performance_summary": performance_summary,
        "dashboard_kpi_summary": dashboard_kpi_summary,
        "assistant_widget_summary": assistant_widget_summary,
        "action_queue_summary": action_queue_summary,
        "suggested_actions": build_suggested_action_cards_for_user(user),
        "actions": actions,
        "quick_replies": [
            "Karnemi nereden görürüm?",
            "Bekleyen görevlerim nerede?",
            "Destek talebi nasıl oluşturulur?",
            "KPI hedefleri nereden takip edilir?",
        ],
        "log_id": log_id,
        "notice": AI_AGENT_DECISION_NOTICE,
        "automation_notice": AI_AGENT_NO_AUTOMATION_NOTICE,
        "security_notice": AI_AGENT_SECURITY_NOTICE,
        "assistant_panel_notice": AI_AGENT_ASSISTANT_PANEL_NOTICE,
    }
# BYS360_AG3_ASSISTANT_CONVERSATION_RUNTIME_END

# BYS360_AG3C_ASSISTANT_PERFORMANCE_CONVERSATION_START
def _ag3c_norm(value):
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("ı", "i")
        .replace("İ", "i")
        .replace("ş", "s")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def _ag3c_action(label, route, description=""):
    return {
        "title": label,
        "label": label,
        "route": route,
        "url": route,
        "description": description,
        "safety_level": "rehber_yonlendirme",
    }


def _ag3c_choice(options):
    try:
        import random
        return random.choice(list(options))
    except Exception:
        return list(options)[0]


def _ag3c_safe_call(name, default, *args, **kwargs):
    fn = globals().get(name)
    if callable(fn):
        try:
            return fn(*args, **kwargs)
        except Exception:
            return default
    return default


def _ag3c_user_id(user):
    return _ag3c_safe_call("_user_id", getattr(user, "id", None), user)


def _ag3c_redact(text):
    return _ag3c_safe_call("redact_sensitive_text", text or "", text or "")


def _ag3c_counts(user):
    return _ag3c_safe_call("collect_safe_counts_for_user", {}, _ag3c_user_id(user))


def _ag3c_performance_summary(user):
    return _ag3c_safe_call("build_ai_agent_performance_summary", {}, user)


def _ag3c_kpi_summary(user):
    return _ag3c_safe_call("build_ai_agent_dashboard_kpi_summary", {}, user)


def _ag3c_widget_summary(user):
    return _ag3c_safe_call("build_ai_agent_assistant_widget_summary", {}, user)


def _ag3c_action_queue(user):
    return _ag3c_safe_call("build_ai_agent_action_queue_summary", {}, user)


def _ag3c_suggested_actions(user):
    return _ag3c_safe_call("build_suggested_action_cards_for_user", [], user)


def _ag3c_any(q, terms):
    return any(term in q for term in terms)


def _ag3c_detect_intent(question):
    q = _ag3c_norm(question)
    short = q.replace(".", "").replace("!", "").replace("?", "").strip()

    greetings = {
        "selam", "slm", "mrb", "merhaba", "hey", "gunaydin", "günaydın",
        "iyi gunler", "iyi günler", "iyi aksamlar", "iyi akşamlar",
        "iyi geceler", "hello", "hi"
    }
    if short in greetings or any(short.startswith(g + " ") for g in greetings):
        return "greeting"

    if _ag3c_any(q, ("nasilsin", "nasılsın", "naber", "ne haber", "iyi misin", "iy misin", "iyimisin", "iyi mısın", "napıyorsun", "napiyorsun")):
        return "small_talk"

    if _ag3c_any(q, ("tesekkur", "teşekkür", "sag ol", "sağ ol", "eyvallah", "cok sagol", "çok sağol")):
        return "thanks"

    if _ag3c_any(q, ("sen kimsin", "kimsin", "adin ne", "adın ne", "nesin", "kendini tanit", "kendini tanıt")):
        return "identity"

    if _ag3c_any(q, ("kim gelistirdi", "kim geliştirdi", "kim yapti", "kim yaptı", "gelistiricin", "geliştiricin", "seni kim", "seni kim gelistirdi", "seni kim geliştirdi", "yapimcin", "yapımcın", "havva gulsen ozden", "havva gülsen özden", "gulsen ozden", "gülsen özden", "havva mi", "havva mı", "gulsen mi", "gülsen mi")):
        return "developer"

    if _ag3c_any(q, ("ne yapabilirsin", "neler yapabilirsin", "yardimci olur musun", "yardımcı olur musun", "nasil yardimci", "nasıl yardımcı")):
        return "assistant_help"

    if _ag3c_any(q, ("performans nedir", "performans sistemi", "performans nasil", "performans nasıl", "performans ne ise yarar", "performans ne işe yarar")):
        return "performance_overview"

    if _ag3c_any(q, ("karnem acilmiyor", "karnem açılmıyor", "karnemi goremiyorum", "karnemi göremiyorum", "puanimi goremiyorum", "puanımı göremiyorum", "sonucum yok", "sonuc gorunmuyor", "sonuç görünmüyor")):
        return "scorecard_not_visible"

    if _ag3c_any(q, ("karne", "karnem", "puanim", "puanım", "sonucum", "sonuç", "sonuc", "gecmis karne", "geçmiş karne")):
        return "my_scorecard"

    if _ag3c_any(q, ("70 alti", "70 altı", "yetmis alti", "yetmiş altı", "dusuk performans", "düşük performans", "basarisiz", "başarısız")):
        return "below_70"

    if _ag3c_any(q, ("baskan onay", "başkan onay", "ust onay", "üst onay", "onaya dustu", "onaya düştü", "onay bekliyor")):
        return "president_approval"

    if _ag3c_any(q, ("bekleyen gorev", "bekleyen görev", "gorevlerim", "görevlerim", "degerlendirme gorev", "değerlendirme görev", "puanlama gorev", "puanlama görev")):
        return "my_tasks"

    if _ag3c_any(q, ("kim degerlendirecek", "kim değerlendirecek", "amir kim", "amirlerim", "beni kim puanlar", "beni kim degerlendirir", "beni kim değerlendirir")):
        return "my_evaluators"

    if _ag3c_any(q, ("1 puan", "bir puan", "5 puan", "bes puan", "beş puan", "aciklama zorunlu", "açıklama zorunlu", "yorum zorunlu")):
        return "score_comment_rules"

    if _ag3c_any(q, ("3 amir", "3. amir", "ucuncu amir", "üçüncü amir", "yorumcu amir")):
        return "third_supervisor"

    if _ag3c_any(q, ("koordinator ne gorur", "koordinatör ne görür", "grup baskani ne gorur", "grup başkanı ne görür", "personel ne gorur", "personel ne görür", "yetki siniri", "yetki sınırı")):
        return "visibility_rules"

    if _ag3c_any(q, ("donem", "dönem", "performans donemi", "performans dönemi", "aylik", "aylık", "3 aylik", "3 aylık", "yillik", "yıllık")):
        return "periods"

    if _ag3c_any(q, ("gecmis", "geçmiş", "arsiv", "arşiv", "eski karne", "2024", "2025")):
        return "archive"

    if _ag3c_any(q, ("gelisim", "gelişim", "onerisi", "önerisi", "rehber", "egitim onerisi", "eğitim önerisi")):
        return "development_guidance"

    if _ag3c_any(q, ("kpi", "hedef", "stratejik", "riskli hedef", "gerceklesme", "gerçekleşme")):
        return "kpi_targets"

    if _ag3c_any(q, ("anket", "geri bildirim", "nabiz", "nabız")):
        return "survey_feedback"

    if _ag3c_any(q, ("destek", "talep", "yardim", "yardım", "ariza", "arıza")):
        return "support"

    if _ag3c_any(q, ("duyuru", "bildirim", "mesaj", "okunmamis", "okunmamış")):
        return "communication"

    if _ag3c_any(q, ("yetki", "rol", "menu", "menü", "ayar", "gorunmuyor", "görünmüyor", "acilmiyor", "açılmıyor")):
        return "settings"

    return "general_help"


def _ag3c_answer_and_actions(intent, counts, performance_summary, dashboard_kpi_summary):
    perf_counts = performance_summary.get("counts", {}) if isinstance(performance_summary, dict) else {}
    kpi_counts = dashboard_kpi_summary.get("counts", {}) if isinstance(dashboard_kpi_summary, dict) else {}

    if intent == "greeting":
        return (
            _ag3c_choice([
                "Merhaba, size nasıl yardımcı olabilirim? Performans karnesi, bekleyen görevler, Başkan/Üst Onay, KPI/Hedefler, destek talepleri, anketler ve bildirimler hakkında soru sorabilirsiniz.",
                "Selam, buradayım. BYS360 içinde hangi işlem için yardım istersiniz?",
                "Merhaba. Karneniz, bekleyen görevleriniz, destek talepleriniz veya KPI/Hedef ekranları için sizi doğru alana yönlendirebilirim.",
            ]),
            [
                _ag3c_action("Karnemi nereden görürüm?", "/performance/scorecard"),
                _ag3c_action("Bekleyen görevlerim", "/performance/tasks"),
                _ag3c_action("Destek taleplerim", "/support"),
            ],
        )

    if intent == "small_talk":
        return (
            _ag3c_choice([
                "İyiyim, teşekkür ederim. BYS360 içinde size yardımcı olmak için buradayım. Bugün hangi işlem için destek istersiniz?",
                "Gayet iyiyim, sağ olun. İsterseniz karneniz, bekleyen görevleriniz veya destek talepleriniz için sizi doğru ekrana yönlendirebilirim.",
                "İyiyim, buradayım. Performans süreci, KPI/Hedefler, anketler veya bildirimler hakkında soru sorabilirsiniz.",
                "Teşekkür ederim, iyiyim. BYS360’da takıldığınız yeri yazmanız yeterli; sizi güvenli şekilde yönlendirebilirim.",
                "İyiyim. Size nasıl yardımcı olabilirim? İsterseniz performans görevlerinden başlayabiliriz.",
                "Buradayım ve hazırım. Karneniz, görevleriniz veya destek taleplerinizle ilgili yardımcı olabilirim.",
            ]),
            [
                _ag3c_action("Performans görevlerim", "/performance/tasks"),
                _ag3c_action("Karneme git", "/performance/scorecard"),
                _ag3c_action("Destek taleplerim", "/support"),
            ],
        )

    if intent == "thanks":
        return (
            _ag3c_choice([
                "Rica ederim. BYS360 içinde ihtiyaç duyduğunuz ekranı bulmak veya süreci anlamak için her zaman yardımcı olabilirim.",
                "Ne demek, memnuniyetle. Başka bir konuda da yardımcı olabilirim.",
                "Rica ederim. İsterseniz sıradaki işlem için sizi doğru ekrana yönlendirebilirim.",
            ]),
            [
                _ag3c_action("Ana sayfaya git", "/home"),
                _ag3c_action("Bildirimler", "/notifications"),
            ],
        )

    if intent == "identity":
        return (
            "Ben BYS360 Asistanı. BYS360 için Havva Gülsen Özden (geliştirici) ve Mustafa Bektaş (eş geliştirici) tarafından geliştirildim. BYS360 içinde kullanıcıları doğru ekrana yönlendirmek, performans ve süreçlerle ilgili güvenli rehberlik sunmak ve yetki dahilindeki özetleri göstermek için tasarlandım.",
            [
                _ag3c_action("Ana sayfa", "/home"),
                _ag3c_action("Destek", "/support"),
            ],
        )

    if intent == "developer":
        return (
            "Beni BYS360 projesi kapsamında Havva Gülsen Özden (geliştirici) ve Mustafa Bektaş (eş geliştirici) geliştirdi. Kurumsal süreçlerde kullanıcıya rehberlik etmek, doğru ekrana yönlendirmek ve güvenli asistan deneyimi sunmak için tasarlandım.",
            [
                _ag3c_action("BYS360 ana sayfa", "/home"),
                _ag3c_action("Yardım ve destek", "/support"),
            ],
        )

    if intent == "assistant_help":
        return (
            "BYS360 içinde size rehberlik edebilirim. Karnenizi bulmanıza, bekleyen görevleri sayı düzeyinde görmenize, Başkan/Üst Onay sürecini anlamanıza, destek talebi ekranına gitmenize, anket ve bildirim alanlarını bulmanıza, KPI/Hedef ekranlarına ulaşmanıza yardımcı olurum. İdari karar vermem, performans puanı üzerinde yetkisiz işlem yapmem ve yetki dışı veri göstermem.",
            [
                _ag3c_action("Performans görevlerim", "/performance/tasks"),
                _ag3c_action("KPI/Hedef paneli", "/performans/stratejik/kpi-dashboard"),
                _ag3c_action("Destek", "/support"),
            ],
        )

    if intent == "performance_overview":
        return (
            "BYS360 Performans Yönetimi; dönem, kriter, amir zinciri, puanlama, açıklama, onay ve yayın süreçlerini birlikte yöneten kurumsal performans yapısıdır. Amaç yalnızca puan vermek değil; süreci ölçülebilir, izlenebilir, adil ve gelişim odaklı hale getirmektir.",
            [
                _ag3c_action("Performans paneli", "/performance/dashboard"),
                _ag3c_action("Karneme git", "/performance/scorecard"),
            ],
        )

    if intent == "scorecard_not_visible":
        return (
            "Karneniz görünmüyorsa süreç henüz yayınlanmamış, Başkan/Üst Onay veya yayın ön onayı tamamlanmamış olabilir. Personel karnesi yalnızca yetkili yayın süreci tamamlandıktan sonra açılır.",
            [
                _ag3c_action("Karneme git", "/performance/scorecard"),
                _ag3c_action("Bildirimler", "/notifications"),
            ],
        )

    if intent == "my_scorecard":
        return (
            "Karnenizi yalnızca yayın ve onay süreci tamamlandıktan sonra görebilirsiniz. Asistan puan veya amir görüşü göstermez; sizi ilgili güvenli ekrana yönlendirir.",
            [
                _ag3c_action("Karneme git", "/performance/scorecard"),
                _ag3c_action("Geçmiş karneler", "/performance/archive"),
            ],
        )

    if intent == "below_70":
        return (
            "70 altı performans sonucu doğrudan kesinleşmez. Bu kayıt üst onay sürecine alınır, gerekli onay ve süreç kaydı tamamlanmadan personele kesin sonuç olarak yayınlanmaz. Sistem otomatik işlem yapmaz; yetkili onay ve idari süreç esastır.",
            [
                _ag3c_action("Başkan Onayları", "/performance/president-approvals"),
                _ag3c_action("Süreç Takibi", "/performance/process-tracking"),
            ],
        )

    if intent == "president_approval":
        count = perf_counts.get("president_approval_waiting", counts.get("president_approval_waiting", 0))
        return (
            f"Yetki kapsamınıza göre Başkan/Üst Onay bekleyen düşük performans kayıt sayısı: {count}. Asistan onay veya ret işlemi yapmaz; ilgili kontrol ekranına yönlendirir.",
            [
                _ag3c_action("Başkan Onayları", "/performance/president-approvals"),
                _ag3c_action("Süreç Takibi", "/performance/process-tracking"),
            ],
        )

    if intent == "my_tasks":
        count = perf_counts.get("pending_assignments", counts.get("pending_performance_assignments", 0))
        return (
            f"Yetki kapsamınıza göre bekleyen performans görevi sayısı: {count}. Görev detayları ve işlem adımları ilgili performans ekranında görüntülenir.",
            [
                _ag3c_action("Performans görevlerim", "/performance/tasks"),
                _ag3c_action("Performans paneli", "/performance/dashboard"),
            ],
        )

    if intent == "my_evaluators":
        return (
            "Performans değerlendirmesinde amir zinciri personelin kurumsal konumuna göre oluşur. Çalışma grubu, koordinatörlük, grup başkanlığı ve özel istisnalar dikkate alınır. Kör değerlendirme yapılmaz; sonraki amir önceki değerlendirmeyi ve kanaati görerek sürece dahil olur.",
            [
                _ag3c_action("Performans görevleri", "/performance/tasks"),
                _ag3c_action("Personel kartı", "/personnel"),
            ],
        )

    if intent == "score_comment_rules":
        return (
            "Açıklama zorunlulukları sistem ayarlarına göre yönetilir. Düşük performans, yüksek başarı veya uç puanlarda açıklama istenebilir. Amaç puanı gerekçelendirmek ve karne sürecini denetlenebilir hale getirmektir.",
            [
                _ag3c_action("Sistem Ayarları", "/settings"),
                _ag3c_action("Rol Matrisi", "/admin/role-matrix"),
            ],
        )

    if intent == "third_supervisor":
        return (
            "3. amir her personelde zorunlu değildir. Sistem ayarına göre yalnızca yorumcu olabilir veya puana katkı veren amir olarak tanımlanabilir. 3. amir yoksa boş görev veya gereksiz sütun gösterilmemelidir.",
            [
                _ag3c_action("Performans ayarları", "/settings"),
                _ag3c_action("Performans görevleri", "/performance/tasks"),
            ],
        )

    if intent == "visibility_rules":
        return (
            "BYS360’da görünürlük yetkiye bağlıdır. Personel kendi karnesini ve kişi detayı içermeyen grup/kategori ortalamasını görür. Koordinatör kendi kapsamını, Grup Başkanı kendi üst birim/grup kapsamını, Başkan ve Admin ise yetkili genel görünümü görür.",
            [
                _ag3c_action("Rol Matrisi", "/admin/role-matrix"),
                _ag3c_action("Performans raporları", "/performance/reports"),
            ],
        )

    if intent == "periods":
        return (
            "Performans dönemleri yıllık, altı aylık, üç aylık, aylık veya özel kapsamlı açılabilir. Dönem tüm kurum, birim, kategori veya seçili personel için tanımlanabilir. Görevler dönem kapsamına göre üretilir.",
            [
                _ag3c_action("Dönemler", "/performance/periods"),
                _ag3c_action("Performans paneli", "/performance/dashboard"),
            ],
        )

    if intent == "archive":
        return (
            "Geçmiş karne ve puan arşivi, önceki dönem performans kayıtlarının yetki bazlı görüntülenmesini sağlar. Personel kendi geçmişini görebilir; yöneticiler yalnızca yetkili oldukları kapsamı görmelidir.",
            [
                _ag3c_action("Geçmiş karneler", "/performance/archive"),
                _ag3c_action("Karneme git", "/performance/scorecard"),
            ],
        )

    if intent == "development_guidance":
        return (
            "Gelişim önerileri performans sonucunu yalnızca puan olarak bırakmamak için kullanılır. Güçlü yönler, gelişim ihtiyacı ve takip önerileri karne sürecini daha rehberlik odaklı hale getirir.",
            [
                _ag3c_action("Gelişim rehberi", "/performance/meeting-development/faz10"),
                _ag3c_action("Karneme git", "/performance/scorecard"),
            ],
        )

    if intent == "kpi_targets":
        risky = kpi_counts.get("risky_targets", counts.get("risky_targets", 0))
        total = kpi_counts.get("total_targets", counts.get("total_targets", 0))
        return (
            f"KPI/Hedef tarafında yetki kapsamınıza göre toplam hedef: {total}, riskli hedef: {risky}. Asistan hedef değeri değiştirmez; analiz ekranına yönlendirir.",
            [
                _ag3c_action("KPI/Hedef paneli", "/performans/stratejik/kpi-dashboard"),
                _ag3c_action("KPI analiz", "/performans/stratejik/kpi-analiz"),
            ],
        )

    if intent == "survey_feedback":
        return (
            "Anket ve geri bildirimlerde asistan cevap içeriği göstermez. Size açık anketleri ve geri bildirim ekranlarını bulmanız için yönlendirme yapar.",
            [
                _ag3c_action("Anketler", "/surveys"),
                _ag3c_action("Geri bildirim", "/communication/feedback"),
                _ag3c_action("Bildirimler", "/notifications"),
            ],
        )

    if intent == "support":
        open_count = counts.get("open_support_tickets", 0)
        return (
            f"Açık destek talebi sayısı: {open_count}. Yeni talep oluşturabilir veya mevcut destek taleplerinizi kontrol edebilirsiniz.",
            [
                _ag3c_action("Destek talebi oluştur", "/support/new"),
                _ag3c_action("Destek taleplerim", "/support"),
            ],
        )

    if intent == "communication":
        return (
            "Duyuru, bildirim ve mesajlarda asistan içerik dökmez; ilgili ekranlara güvenli yönlendirme yapar.",
            [
                _ag3c_action("Bildirimler", "/notifications"),
                _ag3c_action("Duyurular", "/announcements"),
                _ag3c_action("Mesajlar", "/messages"),
            ],
        )

    if intent == "settings":
        return (
            "Rol, menü ve modül görünürlüğü Sistem Ayarları üzerinden yönetilir. Asistan yetki vermez veya kaldırmaz; doğru ayar alanına yönlendirir.",
            [
                _ag3c_action("Rol Matrisi", "/admin/role-matrix"),
                _ag3c_action("Sistem Ayarları", "/settings"),
            ],
        )

    return (
        "Size yardımcı olmak isterim. Performans karnesi, bekleyen görevler, Başkan/Üst Onay, 70 altı süreç, 3. amir, dönemler, geçmiş karne, KPI/Hedefler veya destek talepleri hakkında daha açık bir soru yazabilirsiniz.",
        [
            _ag3c_action("Karnemi nereden görürüm?", "/performance/scorecard"),
            _ag3c_action("Performans görevlerim", "/performance/tasks"),
            _ag3c_action("Destek", "/support"),
        ],
    )


def _legacy_build_ai_agent_reply_ag3c(user, question):
    safe_question = _ag3c_redact(question or "")
    if not safe_question.strip():
        return {
            "ok": False,
            "answer": "Size nasıl yardımcı olabilirim? BYS360 içinde yapmak istediğiniz işlemi kısa bir cümleyle yazabilirsiniz.",
            "actions": [_ag3c_action("Yardım Merkezi", "/support")],
            "notice": globals().get("AI_AGENT_DECISION_NOTICE", "Asistan idari karar vermez ve yetki dışı veri göstermez."),
        }

    intent = _ag3c_detect_intent(safe_question)
    counts = _ag3c_counts(user)
    performance_summary = _ag3c_performance_summary(user)
    dashboard_kpi_summary = _ag3c_kpi_summary(user)
    assistant_widget_summary = _ag3c_widget_summary(user)
    action_queue_summary = _ag3c_action_queue(user)
    answer, actions = _ag3c_answer_and_actions(intent, counts, performance_summary, dashboard_kpi_summary)

    log_id = None
    log_fn = globals().get("insert_agent_request_log")
    if callable(log_fn):
        try:
            log_id = log_fn(
                user_id=_ag3c_user_id(user),
                prompt=safe_question,
                intent=intent,
                response_summary=answer,
            )
        except Exception:
            log_id = None

    return {
        "ok": True,
        "version": "AG-3C Performans Konuşma V1",
        "mode": globals().get("AI_AGENT_MODE_LABEL", "Güvenli rehberlik"),
        "intent": intent,
        "answer": answer,
        "counts": counts,
        "performance_summary": performance_summary,
        "dashboard_kpi_summary": dashboard_kpi_summary,
        "assistant_widget_summary": assistant_widget_summary,
        "action_queue_summary": action_queue_summary,
        "suggested_actions": _ag3c_suggested_actions(user),
        "actions": actions,
        "quick_replies": [
            "Merhaba",
            "İyi misin?",
            "Ne yapabilirsin?",
            "Seni kim geliştirdi?",
            "Karnemi nereden görürüm?",
            "Bekleyen görevlerim nerede?",
            "70 altı olursa ne olur?",
            "3. amir ne yapar?",
            "Performans dönemleri nasıl çalışır?",
        ],
        "log_id": log_id,
        "notice": globals().get("AI_AGENT_DECISION_NOTICE", "Asistan idari karar vermez ve yetki dışı veri göstermez."),
        "automation_notice": globals().get("AI_AGENT_NO_AUTOMATION_NOTICE", "Onayınız olmadan işlem yapılmaz."),
        "security_notice": globals().get("AI_AGENT_SECURITY_NOTICE", "Yetki dışı veri gösterilmez."),
        "assistant_panel_notice": "Merhaba, ben BYS360 Asistanı. Size nasıl yardımcı olabilirim?",
    }
# BYS360_AG3C_ASSISTANT_PERFORMANCE_CONVERSATION_END

# BYS360_AG5_AI_TEACHING_CENTER_SERVICE_START
_AG5_PREVIOUS_BUILD_AI_AGENT_REPLY = _legacy_build_ai_agent_reply_ag3c


def _legacy_build_ai_agent_reply_ag5(user, question):
    try:
        from app.services.ai_agent.knowledge import build_knowledge_reply
        learned_reply = build_knowledge_reply(user, question or '')
        if learned_reply:
            return learned_reply
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/service.py)")
    if callable(_AG5_PREVIOUS_BUILD_AI_AGENT_REPLY):
        try:
            return _AG5_PREVIOUS_BUILD_AI_AGENT_REPLY(user, question)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/service.py)")
    return {'ok': True, 'version': 'AG-5 Öğretilebilir Asistan V1', 'mode': 'Güvenli rehberlik', 'intent': 'general_help', 'answer': "Size yardımcı olmak isterim. BYS360 Asistanı bilgi bankasında uygun kayıt bulunamadı. Sorunuzu işlem adıyla birlikte yazabilir veya Asistan Bilgi Bankası'na yeni kullanım rehberi ekleyebilirsiniz.", 'actions': [{'label':'Asistan Bilgi Bankası','title':'Asistan Bilgi Bankası','route':'/ai-agent/knowledge','url':'/ai-agent/knowledge','description':'BYS360 Asistanına yeni bilgi öğret'}], 'notice':'Asistan idari karar vermez, performans puanı üzerinde yetkisiz işlem yapmez ve yetki dışı veri göstermez.'}
# BYS360_AG5_AI_TEACHING_CENTER_SERVICE_END


# BYS360_ASSISTANT_CANONICAL_GUIDE_V1_START
_BYS360_ASSISTANT_PREV_BUILD_REPLY_V1 = _legacy_build_ai_agent_reply_ag5


def _legacy_build_ai_agent_reply_guide(user, question):
    """BYS360 Asistanı için önce adım adım kullanım rehberini dener."""
    try:
        from app.services.ai_agent.assistant_step_guide import build_bys360_assistant_step_reply
        step_reply = build_bys360_assistant_step_reply(user, question or "")
        if step_reply:
            return step_reply
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/service.py)")
    if callable(_BYS360_ASSISTANT_PREV_BUILD_REPLY_V1):
        return _BYS360_ASSISTANT_PREV_BUILD_REPLY_V1(user, question)
    return {
        "ok": True,
        "version": "BYS360 Asistanı Kullanım Rehberi V1",
        "mode": "Adım adım kurumsal rehberlik",
        "intent": "general_help",
        "answer": "BYS360 Asistanı hazır. BYS360 ekranlarında işlem adımlarını sade şekilde açıklar ve doğru sayfaya yönlendirir.",
        "actions": [{"label": "BYS360 Asistanı Paneli", "title": "BYS360 Asistanı Paneli", "route": "/ai-agent/panel", "url": "/ai-agent/panel"}],
        "notice": "BYS360 Asistanı idari karar vermez, performans puanı üzerinde yetkisiz işlem yapmez ve yetki dışı veri göstermez.",
    }
# BYS360_ASSISTANT_CANONICAL_GUIDE_V1_END


# BYS360_ASSISTANT_KNOWLEDGE_BANK_V1_START
_BYS360_ASSISTANT_PREV_BUILD_REPLY_KB_V1 = _legacy_build_ai_agent_reply_guide


def _legacy_build_ai_agent_reply_kb(user, question):
    """BYS360 Asistanı Bilgi Bankası V1: önce rol bazlı kullanım rehberini dener."""
    try:
        from app.services.ai_agent.assistant_knowledge_bank_v1 import (
            build_bys360_assistant_knowledge_reply,
        )
        kb_reply = build_bys360_assistant_knowledge_reply(user, question or "")
        if kb_reply:
            return kb_reply
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/service.py)")
    if callable(_BYS360_ASSISTANT_PREV_BUILD_REPLY_KB_V1):
        return _BYS360_ASSISTANT_PREV_BUILD_REPLY_KB_V1(user, question)
    return {
        "ok": True,
        "version": "BYS360 Asistanı Bilgi Bankası V1",
        "mode": "Rol bazlı adım adım kullanım rehberi",
        "intent": "general_help",
        "assistant_name": "BYS360 Asistanı",
        "answer": "BYS360 Asistanı hazır. Personel, performans, rol matrisi, destek, anket ve KPI/Hedef ekranlarında adım adım yardımcı olur.",
        "actions": [
            {"label": "BYS360 Asistanı Paneli", "title": "BYS360 Asistanı Paneli", "route": "/ai-agent/panel", "url": "/ai-agent/panel", "safety_level": "rehber_yonlendirme"},
            {"label": "Asistan Bilgi Bankası", "title": "Asistan Bilgi Bankası", "route": "/ai-agent/knowledge", "url": "/ai-agent/knowledge", "safety_level": "rehber_yonlendirme"},
        ],
        "quick_replies": ["Personel nasıl eklenir?", "Performans dönemi nasıl açılır?", "Rol matrisinden menü nasıl açılır?", "KPI hedefleri nerede?"],
        "notice": "BYS360 Asistanı idari karar vermez, puan üretmez ve yetki dışı hassas veri göstermez.",
    }
# BYS360_ASSISTANT_KNOWLEDGE_BANK_V1_END


# BYS360_ASSISTANT_FULL_LIVE_USAGE_GUIDE_V2_START
_BYS360_ASSISTANT_PREV_BUILD_REPLY_FULL_GUIDE_V2 = _legacy_build_ai_agent_reply_kb


def _legacy_build_ai_agent_reply_fullguide(user, question):
    # BYS360 Asistanı V2: önce tam canlı kullanım rehberini dener.
    try:
        from app.services.ai_agent.assistant_full_live_usage_guide_v2 import (
            build_bys360_assistant_full_live_usage_reply,
        )
        guide_reply = build_bys360_assistant_full_live_usage_reply(user, question or "")
        if guide_reply:
            return guide_reply
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/service.py)")
    if callable(_BYS360_ASSISTANT_PREV_BUILD_REPLY_FULL_GUIDE_V2):
        return _BYS360_ASSISTANT_PREV_BUILD_REPLY_FULL_GUIDE_V2(user, question)
    return {
        "ok": True,
        "version": "BYS360 Asistanı Tam Canlı Kullanım Rehberi V2",
        "mode": "Ekran, rol ve süreç bazlı adım adım canlı kullanım rehberi",
        "intent": "general_help",
        "assistant_name": "BYS360 Asistanı",
        "answer": "Merhaba, ben BYS360 Asistanı. BYS360 içinde hangi işlemi nereden yapacağınızı adım adım anlatırım. İdari karar vermem, performans puanı belirlemem ve yetkiniz dışındaki hassas verileri göstermem.",
        "actions": [
            {"label": "BYS360 Asistanı Paneli", "title": "BYS360 Asistanı Paneli", "route": "/ai-agent/panel", "url": "/ai-agent/panel", "safety_level": "rehber_yonlendirme"},
            {"label": "Asistan Bilgi Bankası", "title": "Asistan Bilgi Bankası", "route": "/ai-agent/knowledge", "url": "/ai-agent/knowledge", "safety_level": "rehber_yonlendirme"},
        ],
        "quick_replies": ["Personel nasıl eklenir?", "Performans dönemi nasıl açılır?", "Puanlama ekranı nasıl kullanılır?", "Başkan onayları nasıl kullanılır?", "70 altı performans süreci nasıl ilerler?", "Rol matrisinden menü nasıl açılır?", "İzin ve vekâlet işlemleri nasıl yapılır?", "KPI hedefleri nereden takip edilir?"],
        "notice": "BYS360 Asistanı idari karar vermez, puan üretmez ve yetki dışı hassas veri göstermez.",
    }
# BYS360_ASSISTANT_FULL_LIVE_USAGE_GUIDE_V2_END

# BYS360_ASSISTANT_MASTER_KNOWLEDGE_V3_START
_BYS360_ASSISTANT_PREV_BUILD_REPLY_MASTER_KNOWLEDGE_V3 = _legacy_build_ai_agent_reply_fullguide


def _legacy_build_ai_agent_reply_master(user, question):
    """BYS360 Asistanı V3: kaynak dosya tabanlı proje hafızasını önce dener."""
    try:
        from app.services.ai_agent.assistant_project_master_knowledge_v3 import (
            build_bys360_assistant_master_reply,
        )
        master_reply = build_bys360_assistant_master_reply(user, question or "")
        if master_reply:
            return master_reply
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/service.py)")
    if callable(_BYS360_ASSISTANT_PREV_BUILD_REPLY_MASTER_KNOWLEDGE_V3):
        return _BYS360_ASSISTANT_PREV_BUILD_REPLY_MASTER_KNOWLEDGE_V3(user, question)
    return {
        "ok": True,
        "version": "BYS360 Asistanı Proje Hafızası V3",
        "mode": "Kaynak dosya tabanlı rol, modül, süreç ve güvenlik rehberi",
        "intent": "general_help",
        "assistant_name": "BYS360 Asistanı",
        "answer": "Merhaba, ben BYS360 Asistanı. BYS360 kaynaklarına göre personel, performans, rol matrisi, iletişim, anket, destek, KPI/Hedef ve AI Karar Destek süreçlerini adım adım anlatırım. İdari karar vermem, puan üretmem ve yetki dışı hassas veri göstermem.",
        "actions": [
            {"label": "BYS360 Asistanı Paneli", "title": "BYS360 Asistanı Paneli", "route": "/ai-agent/panel", "url": "/ai-agent/panel", "safety_level": "rehber_yonlendirme"},
            {"label": "Asistan Bilgi Bankası", "title": "Asistan Bilgi Bankası", "route": "/ai-agent/knowledge", "url": "/ai-agent/knowledge", "safety_level": "rehber_yonlendirme"},
        ],
        "quick_replies": ["BYS360 nedir?", "70 altı süreç nasıl ilerler?", "Rol matrisi nasıl çalışır?", "KPI/Hedef ekranları nasıl kullanılır?"],
        "notice": "BYS360 Asistanı idari karar vermez, performans puanı üretmez ve yetki dışı hassas veri göstermez.",
    }
# BYS360_ASSISTANT_MASTER_KNOWLEDGE_V3_END

# BYS360_ASSISTANT_STEPWISE_TUTOR_V4_START
_BYS360_ASSISTANT_PREV_BUILD_REPLY_STEPWISE_TUTOR_V4 = _legacy_build_ai_agent_reply_master


def _legacy_build_ai_agent_reply_stepwise(user, question):
    # BYS360 Asistanı V4: doğal dilde sorulan kullanım sorularını adım adım öğretir.
    try:
        from app.services.ai_agent.assistant_stepwise_tutor_v4 import (
            build_bys360_assistant_stepwise_reply,
        )
        stepwise_reply = build_bys360_assistant_stepwise_reply(user, question or "")
        if stepwise_reply:
            return stepwise_reply
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/service.py)")
    if callable(_BYS360_ASSISTANT_PREV_BUILD_REPLY_STEPWISE_TUTOR_V4):
        return _BYS360_ASSISTANT_PREV_BUILD_REPLY_STEPWISE_TUTOR_V4(user, question)
    return {
        "ok": True,
        "version": "BYS360 Asistanı Öğretici Rehber Motoru V4",
        "mode": "Doğal dil anlama, adım adım kullanım öğretimi ve güvenli yönlendirme",
        "intent": "stepwise_tutor:fallback",
        "assistant_name": "BYS360 Asistanı",
        "answer": "Merhaba, ben BYS360 Asistanı. Bana yapmak istediğiniz işlemi normal cümleyle yazabilirsiniz: ‘personel ekleyeceğim’, ‘performans dönemi açacağım’, ‘menü görünmüyor’, ‘karne nerede?’. Size adım adım işlem sırasını anlatır ve doğru ekrana yönlendiririm. İdari karar vermem, puan üretmem ve yetki dışı hassas veri göstermem.",
        "actions": [
            {"label": "BYS360 Asistanı Paneli", "title": "BYS360 Asistanı Paneli", "route": "/ai-agent/panel", "url": "/ai-agent/panel", "safety_level": "rehber_yonlendirme"},
            {"label": "Yardım/Destek", "title": "Yardım/Destek", "route": "/support", "url": "/support", "safety_level": "rehber_yonlendirme"},
        ],
        "quick_replies": ["Personel nasıl eklenir?", "Performans dönemi nasıl açılır?", "70 altı süreç nasıl ilerler?", "Rol matrisi nasıl çalışır?"],
        "notice": "BYS360 Asistanı idari karar vermez, performans puanı üretmez ve yetki dışı hassas veri göstermez.",
    }
# BYS360_ASSISTANT_STEPWISE_TUTOR_V4_END


# BYS360_ASSISTANT_VISIBLE_TUTOR_V6_HELPER_START
def bys360_visible_tutor_v6_try_answer(message=None, question=None, prompt=None, text=None, **kwargs):
    """Önce V6 bilgi bankasında doğal dil niyet cevabı arar."""
    q = message or question or prompt or text or kwargs.get("q") or kwargs.get("user_message") or ""
    try:
        if bys360_visible_tutor_v6_answer:
            return bys360_visible_tutor_v6_answer(q)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("BYS360 SAFE V6: sessiz yakalanan hata loglandi.")
        return None
    return None
# BYS360_ASSISTANT_VISIBLE_TUTOR_V6_HELPER_END

# BYS360_VISIBLE_TUTOR_V6_1_SERVICE_BRIDGE_START
# Bu blok, eski/çeşitli ai_agent service fonksiyonlarını V6.1 öğretici rehberle güvenli şekilde sarar.
try:
    from app.services.ai_agent.assistant_visible_tutor_v6 import (
        OLD_GREETING as _BYS360_VT_OLD_GREETING,
        WELCOME_TEXT as _BYS360_VT_WELCOME_TEXT,
        try_answer_visible_tutor_v6 as _bys360_vt_try_answer,
    )
except Exception:
    _BYS360_VT_OLD_GREETING = "Merhaba. Ben BYS360 Asistanı. BYS360 içinde performans dönemi oluşturma, personel ekleme, rol matrisi, anket, destek, KPI/Hedef ve karar destek işlemlerinde sizi adım adım yönlendiririm. İdari karar vermem, performans puanı belirlemem, hassas veri göstermem; doğru ekranı, gerekli yetkiyi ve işlem sırasını öğretirim."
    _BYS360_VT_WELCOME_TEXT = "Merhaba. Ben BYS360 Asistanı. BYS360 içinde performans dönemi oluşturma, personel ekleme, rol matrisi, anket, destek, KPI/Hedef ve karar destek işlemlerinde sizi adım adım yönlendiririm. İdari karar vermem, performans puanı belirlemem, hassas veri göstermem; doğru ekranı, gerekli yetkiyi ve işlem sırasını öğretirim."
    def _bys360_vt_try_answer(message: Any = "") -> str:
        return _BYS360_VT_WELCOME_TEXT

def _bys360_vt_extract_message_v6_1(args, kwargs):
    for key in ("message", "question", "prompt", "query", "text", "user_message"):
        if key in kwargs and kwargs.get(key):
            return kwargs.get(key)
    for item in args:
        if isinstance(item, str) and item.strip():
            return item
        if isinstance(item, dict):
            for key in ("message", "question", "prompt", "query", "text", "user_message"):
                if item.get(key):
                    return item.get(key)
    return ""

def _bys360_vt_rewrite_payload_v6_1(result, answer):
    if isinstance(result, str):
        if _BYS360_VT_OLD_GREETING in result:
            return answer or _BYS360_VT_WELCOME_TEXT
        return result
    if isinstance(result, dict):
        changed = False
        for key in ("answer", "reply", "response", "message", "text", "content"):
            value = result.get(key)
            if isinstance(value, str) and _BYS360_VT_OLD_GREETING in value:
                result[key] = answer or _BYS360_VT_WELCOME_TEXT
                changed = True
        if changed:
            result["source"] = "BYS360_VISIBLE_TUTOR_V6_1_REWRITE"
        return result
    return result

def _bys360_vt_wrap_function_v6_1(fn):
    def _wrapped(*args, **kwargs):
        msg = _bys360_vt_extract_message_v6_1(args, kwargs)
        if msg:
            ans = _bys360_vt_try_answer(msg)
            if ans:
                return ans
        result = fn(*args, **kwargs)
        return _bys360_vt_rewrite_payload_v6_1(result, _bys360_vt_try_answer(msg or ""))
    try:
        _wrapped.__name__ = getattr(fn, "__name__", "bys360_visible_tutor_v6_1_wrapped")
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/service.py)")
    return _wrapped

for _bys360_vt_name in (
    "answer", "get_answer", "ask", "reply", "assistant_reply", "generate_reply",
    "generate_ai_agent_reply", "build_response", "build_ai_response", "answer_question",
    "handle_message", "process_message", "get_ai_agent_answer", "bys360_assistant_answer",
):
    _bys360_vt_fn = globals().get(_bys360_vt_name)
    if callable(_bys360_vt_fn) and not getattr(_bys360_vt_fn, "_bys360_visible_tutor_v6_1_wrapped", False):
        _bys360_vt_wrapped = _bys360_vt_wrap_function_v6_1(_bys360_vt_fn)
        _bys360_vt_wrapped._bys360_visible_tutor_v6_1_wrapped = True
        globals()[_bys360_vt_name] = _bys360_vt_wrapped

BYS360_VISIBLE_TUTOR_V6_1_SERVICE_BRIDGE = True
# BYS360_VISIBLE_TUTOR_V6_1_SERVICE_BRIDGE_END

# BYS360_ASSISTANT_FULL_STEPWISE_TUTOR_V5_START
_BYS360_ASSISTANT_PREV_BUILD_REPLY_FULL_TUTOR_V5 = _legacy_build_ai_agent_reply_stepwise

def _legacy_build_ai_agent_reply_fulltutor(user, question):
    try:
        from .assistant_full_stepwise_tutor_v5 import build_bys360_assistant_full_tutor_reply_v5
        return build_bys360_assistant_full_tutor_reply_v5(
            user,
            question,
            legacy_builder=_BYS360_ASSISTANT_PREV_BUILD_REPLY_FULL_TUTOR_V5,
        )
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 Asistanı tam öğretici rehber motoru güvenli yedek moda geçti.")
        previous = globals().get("_BYS360_ASSISTANT_PREV_BUILD_REPLY_FULL_TUTOR_V5")
        if callable(previous):
            try:
                return previous(user, question)
            except Exception:
                __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/service.py)")
        return {
            "ok": True,
            "version": "BYS360 Asistanı Tam Öğretici Rehber Motoru V5",
            "mode": "Güvenli yedek rehberlik",
            "intent": "bys360_stepwise_v5:fallback",
            "assistant_name": "BYS360 Asistanı",
            "answer": "BYS360 Asistanı şu an güvenli yedek modda. Yapmak istediğiniz işlemi normal cümleyle yazabilirsiniz: 'performans dönemi oluşturacağım', 'personel ekleyeceğim', 'menü görünmüyor', 'destek talebi açacağım'. Asistan işlem yapmaz; ilgili BYS360 ekranına adım adım yönlendirir.",
            "actions": [
                {"label": "Ana Sayfa", "title": "Ana Sayfa", "route": "/home", "url": "/home", "safety_level": "rehber_yonlendirme"},
                {"label": "Yardım/Destek", "title": "Yardım/Destek", "route": "/support", "url": "/support", "safety_level": "rehber_yonlendirme"},
            ],
            "quick_replies": ["Performans dönemi nasıl oluşturulur?", "Personel nasıl eklenir?", "Menü görünmüyor ne yapmalıyım?"],
            "notice": "BYS360 Asistanı idari karar vermez, performans puanı belirlemez ve yetki dışı hassas veri göstermez.",
            "error_note": "Asistan geçici olarak güvenli yedek modda çalışıyor.",
        }
# BYS360_ASSISTANT_FULL_STEPWISE_TUTOR_V5_END


# BYS360_ASSISTANT_ASSISTANT_LIKE_V31_START
_BYS360_ASSISTANT_PREV_BUILD_REPLY_ASSISTANT_LIKE_V31 = _legacy_build_ai_agent_reply_fulltutor

def _legacy_build_ai_agent_reply_assistantlike(user, question, context=None):
    # V31.2 final answer bridge: server-first, BYS360-only, home/dashboard ayrımı korunur.
    try:
        from .assistant_chatgpt_like_v31 import build_bys360_assistant_chatgpt_like_reply_v31
        previous: Any = _BYS360_ASSISTANT_PREV_BUILD_REPLY_ASSISTANT_LIKE_V31
        if previous is build_ai_agent_reply:
            previous = None
        return build_bys360_assistant_chatgpt_like_reply_v31(
            user,
            question or "",
            legacy_builder=previous if callable(previous) else None,
            context=context if isinstance(context, dict) else None,
        )
    except Exception:
        if callable(_BYS360_ASSISTANT_PREV_BUILD_REPLY_ASSISTANT_LIKE_V31):
            try:
                return _BYS360_ASSISTANT_PREV_BUILD_REPLY_ASSISTANT_LIKE_V31(user, question)
            except Exception:
                __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/ai_agent/service.py)")
        return {
            "ok": True,
            "marker": "BYS360_ASSISTANT_ASSISTANT_LIKE_V31_SAFE_FALLBACK",
            "answer": "BYS360 Asistanı şu anda sorunuzu güvenli modda yorumluyor. Lütfen yapmak istediğiniz işlemi yazın; personel, performans, rol matrisi, karne, anket, destek veya AI karar destek başlıklarında yönlendirme sağlayabilirim.",
        }
# BYS360_ASSISTANT_ASSISTANT_LIKE_V31_END

# BYS360_ASSISTANT_CURRENT_FINAL_POLISH_V31_3: V31.3 final polish aktif; V31.2 server-first bridge korunur.


# BYS360_ASSISTANT_USAGE_MANUAL_BRAIN_V32_START
_BYS360_ASSISTANT_PREV_BUILD_REPLY_USAGE_MANUAL_V32 = _legacy_build_ai_agent_reply_assistantlike


def build_ai_agent_reply(user, question, context=None):
    """BYS360 Asistanı V32: güncel kullanım kılavuzu tabanlı doğal dil rehberi."""
    try:
        from app.services.ai_agent.assistant_usage_manual_brain_v32 import (
            build_bys360_assistant_usage_manual_reply_v32,
        )
        previous: Any = _BYS360_ASSISTANT_PREV_BUILD_REPLY_USAGE_MANUAL_V32
        if previous is build_ai_agent_reply:
            previous = None
        reply = build_bys360_assistant_usage_manual_reply_v32(
            user,
            question or "",
            legacy_builder=previous if callable(previous) else None,
            context=context if isinstance(context, dict) else None,
        )
        if reply:
            return reply
    except Exception:
        __import__("logging").getLogger(__name__).exception("BYS360 Asistanı V32 kullanım kılavuzu beyni çalışırken hata oluştu.")
    if callable(_BYS360_ASSISTANT_PREV_BUILD_REPLY_USAGE_MANUAL_V32):
        try:
            try:
                return _BYS360_ASSISTANT_PREV_BUILD_REPLY_USAGE_MANUAL_V32(user, question, context=context)
            except TypeError:
                return _BYS360_ASSISTANT_PREV_BUILD_REPLY_USAGE_MANUAL_V32(user, question)
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 Asistanı V32 legacy cevap motoruna dönerken hata oluştu.")
    return {
        "ok": True,
        "version": "BYS360_ASSISTANT_USAGE_MANUAL_BRAIN_V32_SAFE_FALLBACK",
        "intent": "usage_manual_fallback",
        "assistant_name": "BYS360 Asistanı",
        "answer": "Ben BYS360 Asistanı’yım. BYS360 içinde doğru ekranı, işlem sırasını ve güvenli kontrol adımlarını anlatırım. Sorunuzu günlük cümleyle yazabilirsiniz: performans dönemi açacağım, karnemi göremiyorum, menü görünmüyor, destek talebi açacağım gibi.",
        "notice": "BYS360 Asistanı idari karar vermez, performans puanı belirlemez ve yetki dışı hassas veri göstermez.",
        "actions": [{"label": "Ana Sayfa", "title": "Ana Sayfa", "route": "/home", "url": "/home", "safety_level": "rehber_yonlendirme"}],
    }
# BYS360_ASSISTANT_USAGE_MANUAL_BRAIN_V32_END
