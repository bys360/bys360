from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, text

from app.extensions import db

"""BYS360 Performans Aşama 10 — gelişim önerisi ve rehberlik servisi.

Bu servis performans sonucunu yalnızca puanla kapatmamak için kullanılır:
- 70 altı sonuçlarda gelişim önerisi zorunlu/öncelikli kayıt haline gelir.
- 90 üstü sonuçlarda güçlü yön notu tutulabilir.
- Kullanıcıya kısa rehber alanı sunulur.
- Sanal asistan yalnızca rehberlik/yönlendirme sınırında kalır.
- AI karar destek kesin karar vermez; yalnızca dikkat notu üretir.
- Eğitim modülü canlıya açılmaz; ileride ayrı modül olarak genişletilebilir.
"""

logger = logging.getLogger(__name__)

P4_DEVELOPMENT_GUIDANCE_VERSION = "2026-05-01-phase10-development-guidance-binding-v2"
P4_RECOMMENDATION_TABLE = "performance_development_recommendations"

LOW_SCORE_THRESHOLD = 70.0
HIGH_SCORE_THRESHOLD = 90.0

P4_REQUIRED_SETTINGS = {
    "performance_development_recommendations_enabled": {
        "label": "Performans gelişim önerileri aktif",
        "value": "true",
        "description": "Performans sonucundan sonra gelişim önerisi ve güçlü yön notu altyapısını etkinleştirir.",
    },
    "performance_development_recommendation_required_below_70": {
        "label": "70 altı gelişim önerisi zorunlu",
        "value": "true",
        "description": "70 altı sonuçlarda gelişim önerisi oluşturulmasını yayın öncesi kontrol başlığı yapar.",
    },
    "performance_strength_note_enabled_above_90": {
        "label": "90 üstü güçlü yön notu aktif",
        "value": "true",
        "description": "90 üstü sonuçlarda güçlü yön ve iyi uygulama notu tutulmasını destekler.",
    },
    "performance_user_guidance_enabled": {
        "label": "Kullanıcı performans rehberi aktif",
        "value": "true",
        "description": "Personel ve amirler için sade performans kullanım rehberini açar.",
    },
    "performance_virtual_assistant_guidance_enabled": {
        "label": "Sanal asistan rehber yönlendirmesi aktif",
        "value": "true",
        "description": "Sanal asistanın performans ekranlarına yalnızca rehberlik ve yönlendirme yapmasını sağlar.",
    },
    "performance_ai_development_notes_enabled": {
        "label": "AI gelişim dikkat notu aktif",
        "value": "false",
        "description": "AI karar destek notları varsayılan kapalı gelir; açılırsa yalnızca insan denetimli dikkat notu üretir.",
    },
    "performance_ai_no_final_decision": {
        "label": "AI nihai karar vermez",
        "value": "true",
        "description": "AI çıktılarının puan, disiplin veya idari karar yerine geçmeyeceğini sabitler.",
    },
    "performance_development_no_auto_score": {
        "label": "Gelişim önerisi otomatik puan üretmez",
        "value": "true",
        "description": "Gelişim önerisi, ara not veya rehber çıktısı hiçbir şekilde otomatik performans puanı üretmez.",
    },
    "performance_development_no_disciplinary_action": {
        "label": "Gelişim önerisi idari yaptırım üretmez",
        "value": "true",
        "description": "Gelişim önerileri tek başına idari yaptırım, disiplin veya işten çıkarma kararı oluşturmaz.",
    },
    "performance_development_sensitive_data_minimized": {
        "label": "Gelişim önerilerinde hassas veri azaltılır",
        "value": "true",
        "description": "Gelişim ve rehber çıktılarında gereksiz kişisel/hassas içerik gösterilmemesini sağlar.",
    },
}

P4_GUIDANCE_CARDS = [
    {"title": "70 altı sonuç", "text": "Gelişim önerisi ve Başkan onayı süreci birlikte izlenir; sonuç tek başına kesinleşmiş sayılmaz."},
    {"title": "90 üstü sonuç", "text": "Güçlü yön notu ve iyi uygulama görünürlüğü desteklenir; otomatik ödül/işlem üretmez."},
    {"title": "Personel rehberi", "text": "Personel yayın sonrası kendi karne sonucunu, varsa gelişim önerisini ve güçlü yön notunu görebilir."},
    {"title": "Sanal asistan", "text": "Asistan puan, görüş veya hassas içerik göstermez; yalnızca rehberlik ve güvenli yönlendirme sağlar."},
    {"title": "AI karar destek", "text": "AI karar vermez; yalnızca yöneticinin değerlendirmesine yardımcı olacak dikkat notu üretir."},
]

MANAGER_GUIDANCE_ROLES = {
    "admin",
    "super_admin",
    "system_admin",
    "sistem_yoneticisi",
    "baskan",
    "baskan_yardimcisi",
    "grup_baskani",
    "mali_musavir",
    "koordinator",
    "birim_sorumlusu",
}


@dataclass(slots=True)
class P4DevelopmentGuidanceResult:
    ok: bool
    version: str
    settings_seeded: int = 0
    tables_ready: int = 0
    checks_passed: int = 0
    message: str = ""
    warnings: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "version": self.version,
            "settings_seeded": self.settings_seeded,
            "tables_ready": self.tables_ready,
            "checks_passed": self.checks_passed,
            "message": self.message,
            "warnings": list(self.warnings or []),
        }


def _has_table(table_name: str) -> bool:
    try:
        return bool(inspect(db.engine).has_table(table_name))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def _columns(table_name: str) -> set[str]:
    try:
        return {col["name"] for col in inspect(db.engine).get_columns(table_name)}
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return set()


def _scalar(sql: str, params: dict[str, Any] | None = None, default: Any = None) -> Any:
    try:
        return db.session.execute(text(sql), params or {}).scalar()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return default


def _safe_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _setting_exists(setting_key: str) -> bool:
    if not _has_table("module_settings"):
        return False
    return bool(_scalar("""SELECT id FROM module_settings WHERE module_key='performance' AND setting_key=:setting_key LIMIT 1""", {"setting_key": setting_key}))


def _setting_bool(setting_key: str, default: bool = False) -> bool:
    if not _has_table("module_settings"):
        return default
    raw = _scalar("""SELECT value_text FROM module_settings WHERE module_key='performance' AND setting_key=:setting_key LIMIT 1""", {"setting_key": setting_key})
    if raw is None:
        return default
    return str(raw).strip().lower() in {"true", "1", "on", "evet", "aktif", "yes"}


def _insert_module_setting(key: str, payload: dict[str, str]) -> bool:
    cols = _columns("module_settings")
    if not {"module_key", "setting_key"}.issubset(cols):
        return False
    values: dict[str, Any] = {"module_key": "performance", "setting_key": key}
    optional_values = {
        "label": payload.get("label"),
        "value_text": payload.get("value", "true"),
        "value_type": "boolean",
        "description": payload.get("description"),
        "is_active": True,
    }
    for name, value in optional_values.items():
        if name in cols:
            values[name] = value
    names = list(values)
    placeholders = [f":{name}" for name in names]
    if "created_at" in cols:
        names.append("created_at")
        placeholders.append("CURRENT_TIMESTAMP")
    if "updated_at" in cols:
        names.append("updated_at")
        placeholders.append("CURRENT_TIMESTAMP")
    db.session.execute(text(f"INSERT INTO module_settings ({', '.join(names)}) VALUES ({', '.join(placeholders)})"), values)
    return True


def ensure_p4_settings() -> int:
    if not _has_table("module_settings"):
        return 0
    seeded = 0
    for key, payload in P4_REQUIRED_SETTINGS.items():
        if _setting_exists(key):
            continue
        if _insert_module_setting(key, payload):
            seeded += 1
    return seeded


def _canonical_recommendations() -> Any:
    # Tek kanonik sözleşme: Alembic 29fee38a97e1 (47 kolon, Phase-10). Karne ve yayın kapısı
    # aynı "karnede gösterilmesi güvenli" okuyucuyu kullanır.
    from app.performance import phase10_development_guidance_ui

    return phase10_development_guidance_ui


def has_required_development_recommendation(evaluation: Any) -> bool:
    if not evaluation:
        return True
    final_score = _safe_float(getattr(evaluation, "final_total_100", None), default=0.0)
    if final_score >= LOW_SCORE_THRESHOLD:
        return True
    if not _setting_bool("performance_development_recommendation_required_below_70", default=False):
        return True
    return _canonical_recommendations().has_scorecard_safe_recommendation(
        getattr(evaluation, "employee_id", None), getattr(evaluation, "period_id", None)
    )


def get_development_recommendation_publish_block_reason(evaluation: Any) -> str:
    """Yayın ön kontrolü için 70 altı gelişim önerisi eksikliği mesajını döndürür."""
    if not evaluation:
        return ""
    final_score = _safe_float(getattr(evaluation, "final_total_100", None), default=0.0)
    if final_score >= LOW_SCORE_THRESHOLD:
        return ""
    if not _setting_bool("performance_development_recommendation_required_below_70", default=False):
        return ""
    if has_required_development_recommendation(evaluation):
        return ""
    return "70 altı sonuçlarda gelişim önerisi kaydı oluşturulmadan personele yayın açılamaz."


def can_manage_development_guidance(viewer: Any | None) -> bool:
    if viewer is None:
        return False
    role = _safe_text(getattr(viewer, "role", "")).lower()
    return bool(role in MANAGER_GUIDANCE_ROLES or getattr(viewer, "is_admin", False) or getattr(viewer, "is_superuser", False))


def build_scorecard_development_guidance_context(evaluation: Any, viewer: Any | None = None) -> dict[str, Any]:
    final_score = _safe_float(getattr(evaluation, "final_total_100", None), default=0.0) if evaluation else 0.0
    is_low = final_score < LOW_SCORE_THRESHOLD
    is_high = final_score > HIGH_SCORE_THRESHOLD
    # Karne detayı ve PDF aynı kanonik kümeyi gösterir; yönetici dahil hiçbir görüntüleyici
    # taslak/iç kayıt görmez (yönetim akışı Gelişim Rehberi ekranındadır).
    rows = _canonical_recommendations().fetch_scorecard_safe_recommendations(
        getattr(evaluation, "employee_id", None), getattr(evaluation, "period_id", None)
    ) if evaluation else []
    has_required = has_required_development_recommendation(evaluation)
    block_reason = get_development_recommendation_publish_block_reason(evaluation)

    if is_low:
        status_label = "Gelişim önerisi gerekli"
        status_detail = "70 altı sonuç, Başkan onayı sürecinin yanında gelişim önerisiyle desteklenmelidir."
    elif is_high:
        status_label = "Güçlü yön notu eklenebilir"
        status_detail = "90 üstü sonuçlarda güçlü yön, iyi uygulama ve örnek davranış notu tutulabilir."
    else:
        status_label = "Rehberlik alanı"
        status_detail = "Bu sonuç bandında gelişim/güçlü yön notu isteğe bağlıdır; puanı otomatik değiştirmez."

    return {
        "version": P4_DEVELOPMENT_GUIDANCE_VERSION,
        "enabled": _setting_bool("performance_development_recommendations_enabled", default=True),
        "final_score": final_score,
        "is_low_score": is_low,
        "is_high_score": is_high,
        "status_label": status_label,
        "status_detail": status_detail,
        "guidance_cards": P4_GUIDANCE_CARDS,
        "recommendations": rows,
        "count": len(rows),
        "has_required_recommendation": has_required,
        "publish_block_reason": block_reason,
        "can_manage_guidance": can_manage_development_guidance(viewer),
        "ai_note_enabled": _setting_bool("performance_ai_development_notes_enabled", default=False),
        "no_auto_score": _setting_bool("performance_development_no_auto_score", default=True),
        "assistant_guidance_enabled": _setting_bool("performance_virtual_assistant_guidance_enabled", default=True),
    }


def p4_status_checks() -> list[dict[str, Any]]:
    canonical_ready = _canonical_recommendations().ensure_phase10_recommendation_table()
    p8_ready = _setting_exists("performance_interim_notes_enabled") and _has_table("performance_interim_notes")
    live_ai_tables = _has_table("ai_request_logs") or _has_table("ai_recommendations") or _has_table("ai_summary_cache")
    checks = [
        ("p4_development_enabled", "Gelişim önerileri ayarı hazır.", _setting_exists("performance_development_recommendations_enabled")),
        ("p4_recommendation_table", "Gelişim önerisi tablosu hazır.", _has_table(P4_RECOMMENDATION_TABLE)),
        ("p4_recommendation_columns", "Gelişim önerisi tablosu kanonik personel, dönem, görünürlük ve onay alanlarıyla hazır.", canonical_ready),
        ("p4_below_70_required", "70 altı sonuçlarda gelişim önerisi zorunlu/öncelikli kontrol başlığıdır.", _setting_exists("performance_development_recommendation_required_below_70")),
        ("p4_above_90_strength", "90 üstü sonuçlarda güçlü yön notu desteklenir.", _setting_exists("performance_strength_note_enabled_above_90")),
        ("p4_user_guidance", "Kullanıcı rehber alanı ayara bağlandı.", _setting_exists("performance_user_guidance_enabled")),
        ("p4_assistant_guidance", "Sanal asistan yalnızca rehberlik ve yönlendirme için bağlandı.", _setting_exists("performance_virtual_assistant_guidance_enabled")),
        ("p4_ai_human_review", "AI çıktı sınırı insan denetimli karar destek olarak işaretlendi.", _setting_exists("performance_ai_no_final_decision")),
        ("p4_no_auto_score", "Gelişim/rehber notları otomatik puan üretmez.", _setting_exists("performance_development_no_auto_score")),
        ("p4_no_disciplinary_action", "Gelişim önerileri tek başına idari yaptırım üretmez.", _setting_exists("performance_development_no_disciplinary_action")),
        ("p4_sensitive_data_minimized", "Gelişim önerilerinde hassas veri azaltma ilkesi hazır.", _setting_exists("performance_development_sensitive_data_minimized")),
        ("p4_p8_dependency", "Dönem içi notlarla gelişim önerisi bağı korunuyor.", p8_ready),
        ("p4_ai_tables_optional", "AI karar destek canlı omurgası varsa güvenli sınırlarla ilişkilendirilebilir.", bool(live_ai_tables or _setting_exists("performance_ai_development_notes_enabled"))),
    ]
    return [{"code": code, "title": title, "ok": bool(ok), "status": "Hazır" if ok else "Kontrol gerekli"} for code, title, ok in checks]


def run_p4_development_guidance(actor_user_id: int | None = None) -> P4DevelopmentGuidanceResult:
    """Gelişim rehberi ayarlarını hazırlar.

    Öneri tablosunun şeması Alembic'e (29fee38a97e1) aittir; burada tablo oluşturulmaz,
    değiştirilmez ve tabloya kayıt eklenmez.
    """
    warnings: list[str] = []
    seeded = 0
    try:
        seeded = ensure_p4_settings()
        db.session.commit()
    except Exception as exc:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı. | exc=%s", exc)
        db.session.rollback()
        warnings.append("Aşama 10 gelişim/rehberlik hazırlığı tamamlanamadı.")
    checks = p4_status_checks()
    passed = sum(1 for item in checks if item["ok"])
    tables_ready = int(_has_table(P4_RECOMMENDATION_TABLE))
    ok = passed == len(checks)
    return P4DevelopmentGuidanceResult(
        ok=ok,
        version=P4_DEVELOPMENT_GUIDANCE_VERSION,
        settings_seeded=seeded,
        tables_ready=tables_ready,
        checks_passed=passed,
        message="Aşama 10 gelişim önerisi, kullanıcı rehberi, sanal asistan ve AI karar destek sınırları hazır." if ok else "Aşama 10 gelişim/rehberlik kontrollerinde eksik başlık var.",
        warnings=warnings,
    )


__all__ = [
    "P4_DEVELOPMENT_GUIDANCE_VERSION",
    "P4_RECOMMENDATION_TABLE",
    "build_scorecard_development_guidance_context",
    "can_manage_development_guidance",
    "ensure_p4_settings",
    "get_development_recommendation_publish_block_reason",
    "has_required_development_recommendation",
    "run_p4_development_guidance",
]
