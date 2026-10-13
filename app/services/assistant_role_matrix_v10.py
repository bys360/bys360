"""
BYS360 Sanal Asistan Rol Matrisi V10

Amaç:
- Ayarlar ekranında görünür "Sanal Asistan Rol Matrisi" kartı üretmek.
- Sanal Asistan Modülü ana anahtarını rol bazlı aç/kapat yapmak.
- Login, şifre, CAPTCHA, auth, config ve DB bağlantı ayarlarına dokunmaz.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

logger = logging.getLogger(__name__)

try:
    from flask import flash, redirect, request
except Exception:  # pragma: no cover
    logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_role_matrix_v10.py | line=21")
    request = None  # type: ignore[assignment]
    redirect = None  # type: ignore[assignment]
    flash = None  # type: ignore[assignment]

try:
    from flask_login import current_user
except Exception:  # pragma: no cover
    logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_role_matrix_v10.py | line=28")
    current_user = None

try:
    from sqlalchemy import bindparam, inspect, text
except Exception:  # pragma: no cover
    logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_role_matrix_v10.py | line=33")
    text = None  # type: ignore[assignment]

try:
    from app.core.datetime_utils import utc_now
except Exception:  # pragma: no cover
    logger.exception("BYS360 P13B guarded exception | file=app/services/assistant_role_matrix_v10.py | utc_now import")
    from datetime import UTC, datetime

    def utc_now() -> datetime:
        return datetime.now(UTC)

# BYS360_P13B_AUTH001_FIX: bu route yalnizca UI/menu katmaninda degil, backend'de
# de admin ailesine kapali degildi (anonim POST rol matrisini degistirebiliyordu).
# Import basarisiz olursa fail-open olmamasi icin kapali (403) bir fallback kullanilir.
try:
    from app.route_support import admin_required as _bys360_admin_required
except Exception:  # pragma: no cover
    logger.exception("BYS360 P13B guarded exception | file=app/services/assistant_role_matrix_v10.py | admin_required import")

    def _bys360_admin_required(view_func):
        def _fail_closed(*args, **kwargs):
            return ("Yetkisiz erişim.", 403)

        return _fail_closed


ASSISTANT_ROLE_COLUMNS = [
    ("admin", "ADMIN"),
    ("baskan", "BAŞKAN"),
    ("baskan_yardimcisi", "BAŞKAN YARDIMCISI"),
    ("grup_baskani", "GRUP BAŞKANI"),
    ("mali_musavir", "MALİ MÜŞAVİR"),
    ("koordinator", "KOORDİNATÖR"),
    ("birim_sorumlusu", "BİRİM SORUMLUSU"),
    ("personel", "PERSONEL"),
    ("kullanici", "ROLSÜZ/KULLANICI"),
]

ASSISTANT_FEATURE_ROWS = [
    ("assistant_module", "Sanal Asistan Modülü", "Ana anahtar. Kapalı rolde asistan menüsü, sayfası ve tüm kısa yollar görünmez."),
    ("assistant_my_reminders", "Bana Ait Hatırlatmalar", "Kişisel hatırlatma görünümü."),
    ("assistant_scheduled_jobs", "Zamanlanmış İş Planlama", "Zamanlanmış görev ve hatırlatma planlama."),
    ("assistant_report_create", "Rapor Oluşturma", "Asistan üzerinden rapor üretme."),
    ("assistant_report_share", "Rapor Paylaşımı", "Raporu yetki bazlı paylaşma."),
    ("assistant_ai_summary", "AI Özet ve Karar Notu", "AI destekli özet ve yönetici karar notu."),
    ("assistant_process_alerts", "Süreç Hatırlatma ve Uyarılar", "Geciken süreç ve kritik uyarı görünümü."),
    ("assistant_logs", "Asistan İşlem Logları", "Asistan işlem geçmişi ve log görünümü."),
    ("assistant_settings", "Asistan Ayarları", "Asistan yapılandırma alanları."),
]

DEFAULT_ASSISTANT_POLICY: dict[str, set[str]] = {
    "admin": {key for key, _, _ in ASSISTANT_FEATURE_ROWS},
    "baskan": {key for key, _, _ in ASSISTANT_FEATURE_ROWS},
    "baskan_yardimcisi": {key for key, _, _ in ASSISTANT_FEATURE_ROWS},
    "grup_baskani": {key for key, _, _ in ASSISTANT_FEATURE_ROWS},
    "mali_musavir": {key for key, _, _ in ASSISTANT_FEATURE_ROWS},
    "koordinator": {key for key, _, _ in ASSISTANT_FEATURE_ROWS},
    "birim_sorumlusu": {key for key, _, _ in ASSISTANT_FEATURE_ROWS},
    "personel": {"assistant_my_reminders", "assistant_process_alerts"},
    "kullanici": set(),
}


def _normalize(value: Any) -> str:
    raw = "" if value is None else str(value)
    raw = raw.strip().lower()
    raw = raw.replace("ı", "i").replace("İ", "i")
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9]+", "_", raw)
    return re.sub(r"_+", "_", raw).strip("_")


def _db_session():
    try:
        from app.extensions import db
        return db.session
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_role_matrix_v10.py | line=88")
        return None


def _table_columns(session, table_name: str) -> set[str]:
    if text is None or session is None:
        return set()
    table = str(table_name or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        return set()
    try:
        bind = session.get_bind() if hasattr(session, "get_bind") else getattr(session, "bind", None)
        if bind is not None:
            return {str(col.get("name")) for col in inspect(bind).get_columns(table) if col.get("name")}
    except Exception:
        logger.exception("BYS360 settings hardening: table column inspection failed | table=%s", table)
    try:
        rows = session.execute(text(f'PRAGMA table_info("{table}")')).fetchall()
        return {str(row[1]) for row in rows if len(row) > 1}
    except Exception:
        logger.exception("BYS360 settings hardening: sqlite table_info failed | table=%s", table)
        return set()


def _truthy(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    v = str(value).strip().lower()
    if v in {"1", "true", "evet", "yes", "on", "acik", "açık", "enabled"}:
        return True
    if v in {"0", "false", "hayir", "hayır", "no", "off", "kapali", "kapalı", "disabled"}:
        return False
    return None


def _role_defaults_columns(session):
    cols = _table_columns(session, "role_menu_defaults")
    role_col = next((c for c in ("role", "role_key", "role_name", "role_label") if c in cols), None)
    key_col = next((c for c in ("menu_key", "feature_key", "permission_key", "module_key", "key", "code") if c in cols), None)
    value_col = next((c for c in ("is_visible", "visible", "enabled", "is_enabled", "allowed", "value") if c in cols), None)
    return role_col, key_col, value_col, cols


def _get_db_value(session, role: str, feature_key: str) -> bool | None:
    if text is None:
        return None
    role_col, key_col, value_col, _ = _role_defaults_columns(session)
    if not role_col or not key_col or not value_col:
        return None

    candidates = {
        feature_key,
        f"assistant.{feature_key}",
        f"sanal_asistan.{feature_key}",
        "assistant_module" if feature_key == "assistant_module" else feature_key,
        "sanal_asistan" if feature_key == "assistant_module" else feature_key,
    }
    try:
        stmt = text(f"""
            select {value_col}
            from role_menu_defaults
            where lower(cast({role_col} as text)) = lower(:role)
              and lower(cast({key_col} as text)) in :keys
            order by id desc
            limit 1
        """).bindparams(bindparam("keys", expanding=True))
        row = session.execute(stmt, {"role": role, "keys": tuple(_normalize(x) for x in candidates)}).fetchone()
        if row:
            return _truthy(row[0])
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_role_matrix_v10.py | line=161")
        return None
    return None


def _set_db_value(session, role: str, feature_key: str, visible: bool) -> bool:
    if text is None:
        return False
    role_col, key_col, value_col, cols = _role_defaults_columns(session)
    if not role_col or not key_col or not value_col:
        return False

    key = feature_key
    try:
        row = session.execute(text(f"""
            select id
            from role_menu_defaults
            where lower(cast({role_col} as text)) = lower(:role)
              and lower(cast({key_col} as text)) = lower(:key)
            order by id desc
            limit 1
        """), {"role": role, "key": key}).fetchone()

        if row:
            session.execute(text(f"""
                update role_menu_defaults
                set {value_col} = :visible, updated_at = :updated_at
                where id = :id
            """) if "updated_at" in cols else text(f"""
                update role_menu_defaults
                set {value_col} = :visible
                where id = :id
            """), {"visible": visible, "id": row[0], "updated_at": utc_now()})
            return True

        # BYS360_P13B_NEW5_FIX: raw SQL INSERT gecmiste source_type/created_at/
        # updated_at gibi NOT NULL kolonlari atliyordu; bu da ilk-kez-yazilan bir
        # (role, feature) cifti icin INSERT'in constraint ihlaliyle patlamasina ve
        # except blogunun ayni islemde daha once basarili olan UPDATE'leri de
        # rollback ile geri almasina yol aciyordu (kismi/gorunmez veri kaybi).
        insert_cols = [role_col, key_col, value_col]
        insert_placeholders = [":role", ":key", ":visible"]
        insert_params: dict[str, Any] = {"role": role, "key": key, "visible": visible}
        if "source_type" in cols:
            insert_cols.append("source_type")
            insert_placeholders.append(":source_type")
            insert_params["source_type"] = "user_override"
        if "created_at" in cols:
            insert_cols.append("created_at")
            insert_placeholders.append(":created_at")
            insert_params["created_at"] = utc_now()
        if "updated_at" in cols:
            insert_cols.append("updated_at")
            insert_placeholders.append(":updated_at")
            insert_params["updated_at"] = utc_now()

        session.execute(text(f"""
            insert into role_menu_defaults ({", ".join(insert_cols)})
            values ({", ".join(insert_placeholders)})
        """), insert_params)
        return True
    except Exception:
        try:
            session.rollback()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/assistant_role_matrix_v10.py")
        return False


def get_assistant_role_matrix_v10() -> dict[str, Any]:
    session = _db_session()
    matrix: dict[str, dict[str, bool]] = {}

    for feature_key, _, _ in ASSISTANT_FEATURE_ROWS:
        matrix[feature_key] = {}
        for role_key, _ in ASSISTANT_ROLE_COLUMNS:
            value = None
            if session is not None:
                value = _get_db_value(session, role_key, feature_key)
            if value is None:
                value = feature_key in DEFAULT_ASSISTANT_POLICY.get(role_key, set())
            matrix[feature_key][role_key] = bool(value)

    return {
        "roles": ASSISTANT_ROLE_COLUMNS,
        "rows": ASSISTANT_FEATURE_ROWS,
        "matrix": matrix,
    }


def assistant_module_master_enabled_for_role(role_key: str) -> bool:
    data = get_assistant_role_matrix_v10()
    return bool(data["matrix"].get("assistant_module", {}).get(_normalize(role_key), False))


def assistant_role_matrix_v10_save_endpoint():
    if request is None:
        return None

    session = _db_session()
    if session is None:
        if flash:  # type: ignore[truthy-function]
            flash("Sanal Asistan Rol Matrisi kaydedilemedi: DB oturumu bulunamadı.", "danger")
        return redirect(request.referrer or "/settings")

    # R05c / N4: a non-admin changes the baseline column only (every other role is protected);
    # the save is all-or-nothing and audited.
    from app.services.account_change_guard import audit_refusal, is_protected_role, is_real_admin
    from app.services.audit_service import write_audit_log

    current = get_assistant_role_matrix_v10()["matrix"]
    planned = {
        (feature_key, role_key): f"assistant_matrix__{feature_key}__{role_key}" in request.form
        for feature_key, _, _ in ASSISTANT_FEATURE_ROWS
        for role_key, _ in ASSISTANT_ROLE_COLUMNS
    }
    diff = {key: visible for key, visible in planned.items() if bool(current.get(key[0], {}).get(key[1], False)) != visible}
    protected_roles = sorted({role_key for _feature, role_key in diff if is_protected_role(role_key)})
    if protected_roles and not is_real_admin(current_user):
        audit_refusal(None, "assistant_role_matrix_v10:" + ",".join(protected_roles))
        if flash:  # type: ignore[truthy-function]
            flash("Sanal Asistan rol matrisinde personel dışındaki rollerin sütunları yalnız sistem admini tarafından değiştirilebilir.", "danger")
        return redirect(request.referrer or "/settings")

    changed = 0
    failed = False
    for (feature_key, role_key), visible in planned.items():
        if _set_db_value(session, role_key, feature_key, visible):
            changed += 1
        else:
            failed = True
            break

    try:
        if failed:
            raise RuntimeError("assistant role matrix v10: a cell could not be written; nothing is saved")
        write_audit_log(
            "settings.assistant_role_matrix_v10_save",
            "role_menu_default",
            None,
            old_data={f"{feature}:{role}": not visible for (feature, role), visible in diff.items()},
            new_data={f"{feature}:{role}": visible for (feature, role), visible in diff.items()},
            summary=f"assistant role matrix v10: {len(diff)} cell(s) changed",
        )
        session.commit()
        if flash:  # type: ignore[truthy-function]
            flash(f"Sanal Asistan Rol Matrisi kaydedildi. Güncellenen alan: {changed}", "success")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1: Sanal Asistan Rol Matrisi kaydedilemedi | exc=%s", exc)
        try:
            session.rollback()
        except Exception:
            logging.getLogger(__name__).exception("BYS360_MAINTENANCE_V13_P1_SILENT_EXCEPTION_LOGGER | app/services/assistant_role_matrix_v10.py")
        if flash:  # type: ignore[truthy-function]
            flash("Sanal Asistan Rol Matrisi kaydedilemedi.", "danger")

    return redirect(request.referrer or "/settings")


def register_assistant_role_matrix_v10(app):
    @app.context_processor
    def _assistant_role_matrix_v10_context():
        return {
            "assistant_role_matrix_v10": get_assistant_role_matrix_v10,
            "assistant_module_master_enabled_for_role": assistant_module_master_enabled_for_role,
        }

    route = "/settings/assistant-role-matrix-v10/save"
    if route not in {getattr(rule, "rule", "") for rule in app.url_map.iter_rules()}:
        app.add_url_rule(
            route,
            endpoint="assistant_role_matrix_v10_save",
            # BYS360_P13B_AUTH001_FIX: bu satir raw add_url_rule ile hicbir
            # decorator olmadan kayitli oldugu icin anonim POST rol matrisini
            # degistirebiliyordu (Phase 13B AUTH-001, confirmed). Sayfa zaten
            # Ayarlar > admin_required ekraninda sunuldugu icin ayni yetki
            # ailesi backend'de de zorunlu kilinir.
            view_func=_bys360_admin_required(assistant_role_matrix_v10_save_endpoint),
            methods=["POST"],
        )
    return app

# BYS360_ASSISTANT_TABS_ROLE_MATRIX_V2_BEGIN
# Ayarlar ekranındaki ek Sanal Asistan matrisi de gerçek BYS360 Asistanı sekmelerini gösterir.
_BYS360_ASSISTANT_TAB_FEATURE_ROWS = [
    ("assistant_module", "BYS360 Asistanı Modülü", "Ana anahtar. Kapalı rolde Asistan bölümü, paneli ve tüm alt sekmeler görünmez."),
    ("ai_agent_panel", "Asistan Paneli", "BYS360 Asistanı sohbet/rehber paneli."),
    ("ai_agent_knowledge", "Asistan Bilgi Bankası", "Asistanın kurumsal bilgi kayıtlarının yönetildiği ekran."),
    ("ai_agent_teaching_center", "Asistan Öğretim Merkezi", "Asistan eğitim/öğretim merkezi ekranı."),
]
try:
    _existing_rows = {_row[0] for _row in ASSISTANT_FEATURE_ROWS}
    _prepend_rows = [_row for _row in _BYS360_ASSISTANT_TAB_FEATURE_ROWS if _row[0] not in _existing_rows]
    ASSISTANT_FEATURE_ROWS = _prepend_rows + list(ASSISTANT_FEATURE_ROWS)
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/assistant_role_matrix_v10.py)")
_BYS360_ASSISTANT_TAB_DEFAULTS = {
    "admin": {'assistant_module', 'ai_agent_panel', 'ai_agent_knowledge', 'ai_agent_teaching_center'},
    "baskan": {'assistant_module', 'ai_agent_panel', 'ai_agent_knowledge', 'ai_agent_teaching_center'},
    "baskan_yardimcisi": {'assistant_module', 'ai_agent_panel'},
    "grup_baskani": {'assistant_module', 'ai_agent_panel'},
    "mali_musavir": {'assistant_module', 'ai_agent_panel'},
    "koordinator": {'assistant_module', 'ai_agent_panel'},
    "birim_sorumlusu": {'assistant_module', 'ai_agent_panel'},
    "personel": {'assistant_module', 'ai_agent_panel'},
    "kullanici": set(),
}
try:
    for _role, _keys in _BYS360_ASSISTANT_TAB_DEFAULTS.items():
        DEFAULT_ASSISTANT_POLICY.setdefault(_role, set()).update(_keys)
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/services/assistant_role_matrix_v10.py)")
# BYS360_ASSISTANT_TABS_ROLE_MATRIX_V2_END
