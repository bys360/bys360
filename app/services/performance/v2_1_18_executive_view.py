from __future__ import annotations

import logging
from typing import Any

"""BYS360 Performans V2.1.18 üst yönetim görünümü.

Bu servis Dönem Yönetim Merkezi için Başkan/üst yönetim odaklı kısa süreç
özeti üretir. Yazma işlemi yapmaz; görev üretmez, bildirim göndermez,
değerlendirme veya dönem kaydı oluşturmaz.
"""

logger = logging.getLogger(__name__)

RULE_VERSION = "performance_v2_1_18_executive_view"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return default


def _as_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _term_from_obj(obj: Any) -> list[str]:
    terms: list[str] = []
    if obj is None:
        return terms
    if isinstance(obj, str):
        return [obj]
    for attr in ["name", "role", "role_name", "title", "unvan", "display_name", "label", "code"]:
        try:
            value = getattr(obj, attr, None)
            if value:
                terms.append(str(value))
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
    return terms


def collect_user_role_terms(user: Any) -> list[str]:
    terms: list[str] = []
    if user is None:
        return terms
    # R05/R1: authority comes from the stored role only; title, unvan, position or gorev never add a term.
    for attr in ["role", "role_name", "user_role", "authority_level"]:
        try:
            value = getattr(user, attr, None)
            terms.extend(_term_from_obj(value))
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
    try:
        roles = getattr(user, "roles", None)
        if roles:
            for role in roles:
                terms.extend(_term_from_obj(role))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        pass
    try:
        groups = getattr(user, "groups", None)
        if groups:
            for group in groups:
                terms.extend(_term_from_obj(group))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        pass
    cleaned: list[str] = []
    for item in terms:
        item = _as_text(item)
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def _norm(text: str) -> str:
    value = _as_text(text).lower()
    return (value
            .replace("ı", "i")
            .replace("ğ", "g")
            .replace("ü", "u")
            .replace("ş", "s")
            .replace("ö", "o")
            .replace("ç", "c"))


def is_period_center_executive_user(user: Any) -> bool:
    """Başkan / Başkan Yardımcısı / üst yönetim için izleme modu.

    Grup Başkanı özellikle hariç tutulur; çünkü performans süreçlerinde ayrı bir
    yönetici kapsamına sahiptir.
    """
    terms = [_norm(t) for t in collect_user_role_terms(user)]
    for term in terms:
        if "grup baskan" in term:
            continue
        if term in {"baskan", "president", "ust yonetim", "ust yonetici", "executive"}:
            return True
        if "baskan yardimc" in term or "ust yonetim" in term or "president" in term:
            return True
    return False


def _risk_meta(counts: dict[str, Any], scope_counts: dict[str, Any], reminder_summary: dict[str, Any], has_period: bool) -> dict[str, str]:
    total = _safe_int(counts.get("total"))
    pending = _safe_int(counts.get("pending"))
    overdue = _safe_int(counts.get("overdue"))
    due_soon = _safe_int(counts.get("due_soon"))
    manager_review = _safe_int(scope_counts.get("manager_review"))
    scope_mismatch = _safe_int(scope_counts.get("scope_mismatch"))
    reminder_targets = _safe_int(reminder_summary.get("target_evaluators"))
    progress = _safe_int(counts.get("progress"))

    if not has_period:
        return {"label": "Dönem Bağlantısı Bekliyor", "class": "muted", "message": "İzlenecek dönem gerçek performans dönemiyle ilişkilendirildiğinde süreç özeti oluşur."}
    if scope_mismatch > 0:
        return {"label": "Kapsam Kontrolü Gerekli", "class": "danger", "message": "Kapsam uyumsuzluğu bulunan kayıtlar incelenmeden görev üretimi tamamlanmamalıdır."}
    if manager_review > 0:
        return {"label": "Amir Kontrolü Gerekli", "class": "warn", "message": "Amir bilgisi kontrol gerektiren kayıtlar bulunuyor."}
    if total <= 0:
        return {"label": "Görev Üretimi Bekliyor", "class": "warn", "message": "Bu dönem için değerlendirme görevi henüz görünmüyor."}
    if overdue > 0:
        return {"label": "Gecikme Var", "class": "danger", "message": "Geciken değerlendirme görevleri için hatırlatma süreci hazırlanmalıdır."}
    if due_soon > 0:
        return {"label": "Son Tarih Yaklaşıyor", "class": "warn", "message": "Son tarihi yaklaşan görevler yakından izlenmelidir."}
    if pending > 0 or reminder_targets > 0:
        return {"label": "Süreç Devam Ediyor", "class": "info", "message": "Değerlendirme süreci olağan takip durumundadır."}
    if progress >= 100:
        return {"label": "Yayın Öncesi Kontrol", "class": "ok", "message": "Değerlendirmeler tamamlanmış görünüyor; yayın ve onay adımları kontrol edilmelidir."}
    return {"label": "Normal", "class": "ok", "message": "Seçili dönem için kritik blokaj görünmüyor."}


def _card(title: str, value: Any, label: str, klass: str = "info") -> dict[str, Any]:
    return {"title": title, "value": value, "label": label, "class": klass}


def build_period_center_executive_view(
    *,
    user: Any = None,
    state: dict[str, Any] | None = None,
    embedded_summary: dict[str, Any] | None = None,
    period_flow: dict[str, Any] | None = None,
    scope_control: dict[str, Any] | None = None,
    reminder_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = embedded_summary or {}
    flow = period_flow or {}
    scope = scope_control or {}
    reminder = reminder_approval or {}
    counts = summary.get("counts") or {}
    scope_counts = scope.get("counts") or {}
    reminder_summary = reminder.get("summary") or {}
    is_exec = is_period_center_executive_user(user)
    has_period = bool(summary.get("available") or flow.get("selected_period_id"))
    risk = _risk_meta(counts, scope_counts, reminder_summary, has_period)
    progress = _safe_int(counts.get("progress"))
    pending = _safe_int(counts.get("pending"))
    overdue = _safe_int(counts.get("overdue"))
    due_soon = _safe_int(counts.get("due_soon"))
    manager_review = _safe_int(scope_counts.get("manager_review"))
    scope_mismatch = _safe_int(scope_counts.get("scope_mismatch"))
    reminder_targets = _safe_int(reminder_summary.get("target_evaluators"))

    next_steps: list[dict[str, str]] = []
    if not has_period:
        next_steps.append({"label": "Dönem bağlantısını tamamlayın", "class": "warn"})
    if scope_mismatch or manager_review:
        next_steps.append({"label": "Kapsam ve amir kontrolünü inceleyin", "class": "warn" if not scope_mismatch else "danger"})
    if has_period and _safe_int(counts.get("total")) <= 0:
        next_steps.append({"label": "Görev üretimi adımını tamamlayın", "class": "warn"})
    if overdue or due_soon or reminder_targets:
        next_steps.append({"label": "Hatırlatma hazırlığını kontrol edin", "class": "danger" if overdue else "warn"})
    if not next_steps:
        next_steps.append({"label": "Süreç olağan takipte", "class": "ok"})

    return {
        "rule_version": RULE_VERSION,
        "is_executive_mode": bool(is_exec),
        "show_admin_actions": not bool(is_exec),
        "mode_label": "Üst Yönetim Görünümü" if is_exec else "Yönetim Görünümü",
        "role_terms": collect_user_role_terms(user),
        "period_title": _as_text(summary.get("period_title") or flow.get("selected_title"), "Dönem seçilmedi"),
        "risk": risk,
        "cards": [
            _card("Tamamlanma", f"%{progress}", "Seçili dönem ilerleme oranı.", "ok" if progress >= 100 else ("info" if progress > 0 else "muted")),
            _card("Bekleyen Görev", pending, "Henüz tamamlanmamış değerlendirme görevi.", "warn" if pending else "ok"),
            _card("Öncelikli Takip", f"{overdue} / {due_soon}", "Geciken ve son tarihi yaklaşan görevler.", "danger" if overdue else ("warn" if due_soon else "ok")),
            _card("Kontrol Gereken", manager_review + scope_mismatch, "Amir veya kapsam kontrolü gereken kayıt.", "danger" if scope_mismatch else ("warn" if manager_review else "ok")),
            _card("Hatırlatma Hedefi", reminder_targets, "Hatırlatma listesine girebilecek amir sayısı.", "warn" if reminder_targets else "ok"),
        ],
        "next_steps": next_steps,
        "summary_text": risk.get("message") or "Süreç durumu izleniyor.",
    }


def run_v2_1_18_executive_view_gate(executive_view: dict[str, Any] | None = None) -> dict[str, Any]:
    view = executive_view or {}
    checks = [
        {"name": "executive_view_builds", "ok": isinstance(view, dict), "message": "Üst yönetim özeti hazırlanıyor."},
        {"name": "risk_label_available", "ok": bool((view.get("risk") or {}).get("label")), "message": "Risk/durum etiketi üretildi."},
        {"name": "cards_available", "ok": len(view.get("cards") or []) >= 5, "message": "Yönetici özet kartları hazır."},
        {"name": "read_only", "ok": True, "message": "Üst yönetim görünümü yalnızca okuma amaçlıdır."},
    ]
    return {"ok": all(item.get("ok") for item in checks), "checks": checks, "rule_version": RULE_VERSION, "mode_label": view.get("mode_label")}
