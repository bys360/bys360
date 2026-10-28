from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import inspect, text

from app.services.performance.v2_1_2_category_engine import seed_default_categories
from app.services.performance.v2_1_4_category_scope_visibility import (
    category_scope_dashboard_summary,
    ensure_category_scope_schema,
)
from app.services.performance.v2_1_5_category_period_scope import (
    PERIOD_TYPES,
    PLAN_STATUSES,
    assignment_precheck_for_plan,
    category_period_scope_summary,
    ensure_category_period_scope_schema,
    list_category_period_scope_plans,
    list_plan_items,
    preview_category_period_scope,
    upsert_category_period_scope_plan,
)
from app.services.performance.v2_1_6_category_period_integration import (
    build_assignment_preintegration,
    create_or_update_period_from_plan,
    ensure_category_period_integration_schema,
    integration_summary,
    list_integrations,
    list_preintegration_rows,
)
from app.services.performance.v2_1_6a_category_ui_cleanup import active_categories

"""BYS360 Performans V2.1.7 dönem yönetim merkezi servis katmanı.

V2.1.8A HOTFIX: İlk sayfa açılışını hafifletir. Plan otomatik seçilmez,
ağır personel/amir ön kontrol listeleri yalnızca kullanıcı plan seçtiğinde
üretilir. Böylece Dönem Yönetim Merkezi ekranda dönerek kalmaz.
"""

logger = logging.getLogger(__name__)

RULE_VERSION = "performance_v2_1_8a_period_center_fast_open_hotfix"
CENTER_ROUTE = "main.performance_v2_1_7_period_management_center"
CENTER_PATH = "/performance/v2-1-7-period-management-center"
CENTER_PATH_TR = "/performans/donem-yonetim-merkezi"


def _db():
    from app.extensions import db
    return db


def _safe_call(fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        try:
            _db().session.rollback()
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
        return default


def _has_table(table_name: str) -> bool:
    try:
        return bool(inspect(_db().engine).has_table(table_name))
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return False


def _count_table(table_name: str) -> int:
    if not _has_table(table_name):
        return 0
    try:
        return int(_db().session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        try:
            _db().session.rollback()
        except Exception:
            logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
            pass
        return 0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        logger.exception("BYS360 performans modülünde beklenmeyen hata yakalandı.")
        return default


def ensure_period_management_center_ready() -> dict[str, Any]:
    """Alt servis şemalarını hazırlar; ayrıca görev üretimi yapmaz."""
    seed = _safe_call(lambda: seed_default_categories(overwrite=False), {"ok": False})
    scope = _safe_call(lambda: ensure_category_scope_schema(), {"ok": False})
    period_scope = _safe_call(lambda: ensure_category_period_scope_schema(), {"ok": False})
    integration = _safe_call(lambda: ensure_category_period_integration_schema(), {"ok": False})
    return {
        "ok": True,
        "rule_version": RULE_VERSION,
        "seed": seed,
        "scope": scope,
        "period_scope": period_scope,
        "integration": integration,
    }


def _find_plan(plans: list[dict[str, Any]], plan_key: str | None) -> dict[str, Any] | None:
    key = str(plan_key or "").strip()
    if not key:
        return None
    return next((p for p in plans if str(p.get("plan_key") or "") == key), None)


def _find_integration(integrations: list[dict[str, Any]], plan_key: str | None) -> dict[str, Any] | None:
    key = str(plan_key or "").strip()
    if not key:
        return None
    return next((p for p in integrations if str(p.get("plan_key") or "") == key), None)


def _step(key: str, title: str, ok: bool, message: str, *, warn: bool = False) -> dict[str, Any]:
    if ok:
        state = "ok"
        label = "Tamamlandı"
    elif warn:
        state = "warn"
        label = "Kontrol Gerekli"
    else:
        state = "muted"
        label = "Bekliyor"
    return {"key": key, "title": title, "ok": bool(ok), "state": state, "label": label, "message": message}


def _period_quality_counts() -> dict[str, int]:
    return {
        "criteria_count": _count_table("performance_criteria"),
        "weight_config_count": _count_table("performance_weight_configs"),
        "period_count": _count_table("performance_periods"),
        "assignment_count": _count_table("evaluation_assignments"),
    }


def build_wizard_steps(
    *,
    selected_plan: dict[str, Any] | None,
    selected_integration: dict[str, Any] | None,
    selected_category_preview: dict[str, Any],
    precheck_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts = _period_quality_counts()
    personnel_count = _safe_int(selected_category_preview.get("active_personnel_count"))
    plan_ready = bool(selected_plan and (selected_plan.get("ready_for_assignment") or selected_plan.get("plan_status") == "ready"))
    linked = bool(selected_integration and selected_integration.get("period_id"))
    pre_ready = bool(selected_integration and selected_integration.get("assignment_precheck_status") == "ready")
    pre_warn = bool(selected_integration and selected_integration.get("assignment_precheck_status") not in {None, "", "ready", "not_started"})
    generation_status = str((selected_integration or {}).get("assignment_generation_status") or "")
    generated = generation_status == "generated"
    generation_warn = generation_status in {"failed", "blocked"}
    return [
        _step("period_info", "1. Dönem Bilgileri", bool(selected_plan), "Dönem adı, türü ve tarih aralığı hazırlanır." if not selected_plan else "Dönem hazırlık planı oluşturuldu."),
        _step("scope", "2. Kapsam Seçimi", personnel_count > 0, f"Seçili kapsamda {personnel_count} aktif personel var." if personnel_count > 0 else ("Plan seçildiğinde kapsam personeli hızlı ön izlemede gösterilir." if not selected_plan else "Kapsamda personel görünmüyor; kategori/personel atamalarını kontrol edin."), warn=bool(selected_plan and personnel_count == 0)),
        _step("criteria", "3. Kriter Kontrolü", counts["criteria_count"] > 0, f"Tanımlı değerlendirme kriteri: {counts['criteria_count']}" if counts["criteria_count"] > 0 else "Değerlendirme kriterleri tanımlanmalı.", warn=counts["criteria_count"] == 0),
        _step("weights", "4. Ağırlık Kontrolü", counts["weight_config_count"] > 0, f"Ağırlık yapılandırması: {counts['weight_config_count']} kayıt" if counts["weight_config_count"] > 0 else "1./2./3. amir ağırlıkları kontrol edilmeli.", warn=counts["weight_config_count"] == 0),
        _step("plan", "5. Dönem Planı", plan_ready, "Plan görev üretimi öncesi hazırlığa uygun." if plan_ready else ("Bir plan seçin veya yeni plan hazırlayın." if not selected_plan else "Plan tarih, kapsam veya personel nedeniyle kontrol istiyor."), warn=bool(selected_plan and not plan_ready)),
        _step("link", "6. Gerçek Döneme Bağlantı", linked, "Plan gerçek performans dönemine bağlandı." if linked else "Plan henüz gerçek performans dönemine bağlanmadı."),
        _step("precheck", "7. Amir ve Görev Ön Kontrolü", pre_ready, f"Ön kontrol tamamlandı. Satır sayısı: {len(precheck_rows)}" if pre_ready else "Görev üretiminden önce amir/kapsam kontrolü yapılmalı.", warn=pre_warn),
        _step("assignment_launch", "8. Görev Üretimi", generated, "Değerlendirme görevleri üretildi ve süreç başlatıldı." if generated else ("Görev üretimi güvenlik kapısında durdu; kontrol panelindeki uyarıları inceleyin." if generation_warn else "Ön kontroller temizlendikten sonra görev üretimi başlatılabilir."), warn=generation_warn),
    ]


def _empty_preview(category_key: str = "") -> dict[str, Any]:
    return {
        "ok": True,
        "category_key": category_key,
        "display_name": "Plan seçilmedi",
        "active_personnel_count": 0,
        "personnel": [],
        "message": "Sayfa hızlı açılsın diye kapsam listesi plan seçilince yüklenir.",
    }


def build_period_management_center_state(selected_plan_key: str | None = None, selected_category_key: str | None = None) -> dict[str, Any]:
    ensure_period_management_center_ready()
    cats = _safe_call(lambda: active_categories(), [])
    plans = _safe_call(lambda: list_category_period_scope_plans(include_inactive=False), [])
    integrations = _safe_call(lambda: list_integrations(), [])

    requested_plan_key = str(selected_plan_key or "").strip()
    selected_plan = _find_plan(plans, requested_plan_key)
    # V2.1.8A: İlk açılışta otomatik ilk planı seçme. Büyük veri setlerinde sayfa dönerek kalabiliyordu.
    selected_plan_key = str(selected_plan.get("plan_key") or "") if selected_plan else ""

    selected_integration = _find_integration(integrations, selected_plan_key) if selected_plan_key else None
    if selected_category_key:
        category_key = str(selected_category_key or "")
    elif selected_plan:
        category_key = str(selected_plan.get("category_key") or "")
    elif cats:
        category_key = str(getattr(cats[0], "category_key", "diger"))
    else:
        category_key = "diger"

    if selected_plan_key:
        selected_preview = _safe_call(lambda: preview_category_period_scope(category_key, include_person_details=False, limit=80), _empty_preview(category_key))
        plan_items = _safe_call(lambda: list_plan_items(selected_plan_key, include_person_details=False, limit=40), [])
        precheck = _safe_call(lambda: assignment_precheck_for_plan(selected_plan_key), {"ok": False, "checks": [], "message": "Ön kontrol alınamadı."})
        period_id = _safe_int((selected_integration or {}).get("period_id"))
        pre_rows = _safe_call(lambda: list_preintegration_rows(selected_plan_key, period_id or None, limit=80), []) if period_id else []
    else:
        selected_preview = _empty_preview(category_key)
        plan_items = []
        precheck = {"ok": False, "checks": [], "message": "Plan seçilmedi."}
        pre_rows = []

    steps = build_wizard_steps(
        selected_plan=selected_plan,
        selected_integration=selected_integration,
        selected_category_preview=selected_preview,
        precheck_rows=pre_rows,
    )
    ready_steps = sum(1 for item in steps if item.get("state") == "ok")
    warning_steps = sum(1 for item in steps if item.get("state") == "warn")
    status_label = "Görev üretimine hazır" if ready_steps == len(steps) else ("Kontrol gerekli" if warning_steps else "Hazırlık sürüyor")
    return {
        "rule_version": RULE_VERSION,
        "categories": cats,
        "period_types": PERIOD_TYPES,
        "plan_statuses": PLAN_STATUSES,
        "plans": plans,
        "integrations": integrations,
        "selected_plan": selected_plan,
        "selected_plan_key": selected_plan_key,
        "selected_integration": selected_integration,
        "selected_category_key": category_key,
        "selected_preview": selected_preview,
        "plan_items": plan_items,
        "precheck": precheck,
        "pre_rows": pre_rows,
        "steps": steps,
        "ready_steps": ready_steps,
        "warning_steps": warning_steps,
        "status_label": status_label,
        "category_summary": _safe_call(lambda: category_scope_dashboard_summary(), {"category_count": len(cats)}),
        "period_scope_summary": _safe_call(lambda: category_period_scope_summary(), {"plan_count": len(plans)}),
        "integration_summary": _safe_call(lambda: integration_summary(), {"integration_count": len(integrations), "preintegration_row_count": 0}),
        "quality_counts": _period_quality_counts(),
    }


def create_center_period_plan(
    *,
    category_key: str,
    plan_name: str | None,
    period_type: str,
    start_date: Any,
    end_date: Any,
    notes: str | None,
    created_by: int | None,
    scope_visibility_mode: str = "summary_only",
    link_period: bool = False,
    activate_period: bool = False,
    run_precheck: bool = False,
) -> dict[str, Any]:
    # D1: bağlanacak plan, dönem bağlamasıyla aynı işlemde yazılır. Bağlama korunan dönemi kilitli
    # satırda reddederse (ensure_plan_relink_allowed) plan kaydı da geri alınır; kısmi değişiklik kalmaz.
    plan_result = upsert_category_period_scope_plan(
        category_key=category_key,
        plan_name=plan_name,
        period_type=period_type,
        start_date=start_date,
        end_date=end_date,
        notes=notes,
        created_by=created_by,
        scope_visibility_mode=scope_visibility_mode,
        commit=not link_period,
    )
    result: dict[str, Any] = {"ok": bool(plan_result.get("ok")), "plan": plan_result, "rule_version": RULE_VERSION}
    plan_key = str(plan_result.get("plan_key") or "")
    if link_period and plan_key:
        link_result = create_or_update_period_from_plan(plan_key, created_by=created_by, activate_period=activate_period)
        if not link_result.get("ok"):
            _db().session.commit()  # bağlanamayan plan önceden olduğu gibi kaydedilir
        result["link"] = link_result
        if run_precheck and link_result.get("ok"):
            precheck_result = build_assignment_preintegration(plan_key, int(link_result.get("period_id") or 0), write=True)
            result["precheck"] = precheck_result
    return result
