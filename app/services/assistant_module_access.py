"""
BYS360 Sanal Asistan modül erişimi.

Bu servis yalnızca Sanal Asistan modülünün rol bazlı görünürlüğünü ve
asistan sayfalarına doğrudan erişim kontrolünü yönetir.
Login, parola, CAPTCHA, auth, config veya DB bağlantı ayarlarına dokunmaz.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

logger = logging.getLogger(__name__)

try:
    from flask import abort, redirect, request, url_for
    from flask_login import current_user
except Exception:  # pragma: no cover
    logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=22")
    abort = None  # type: ignore[assignment]
    request = None  # type: ignore[assignment]
    redirect = None  # type: ignore[assignment]
    url_for = None  # type: ignore[assignment]
    current_user = None

try:
    from sqlalchemy import bindparam, text
except Exception:  # pragma: no cover
    logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=31")
    text = None  # type: ignore[assignment]


ASSISTANT_MASTER_KEYS = {
    "assistant_module",
    "sanal_asistan",
    "sanal_asistan_modulu",
    "sanal_asistan_modülü",
    "assistant",
    "asistan",
}

ASSISTANT_PATH_KEYWORDS = (
    "/assistant",
    "/asistan",
    "/virtual-assistant",
    "/sanal-asistan",
)

ASSISTANT_TEXT_LABELS = (
    "Sanal Asistan",
    "Asistan",
    "Asistan Merkezi",
    "Sanal Asistan Merkezi",
    "Zamanlanmış İş Planlama",
    "Rapor Oluşturma",
    "Rapor Paylaşımı",
    "AI Özet ve Karar Notu",
    "Süreç Hatırlatma",
    "Asistan İşlem Logları",
    "Asistan Ayarları",
)

ASSISTANT_SHORTCUT_KEYS = {
    "assistant_center",
    "assistant_my_reminders",
    "assistant_scheduled_jobs",
    "assistant_report_create",
    "assistant_report_share",
    "assistant_ai_summary",
    "assistant_process_alerts",
    "assistant_logs",
    "assistant_settings",
}

OPEN_ROLES = {
    "admin",
    "sistem_yoneticisi",
    "baskan",
    "baskan_yardimcisi",
    "grup_baskani",
    "mali_musavir",
    "koordinator",
    "birim_sorumlusu",
    "personel_yonetimi_yetkilisi",
    "performans_yetkilisi",
    "iletisim_yetkilisi",
    "ai_karar_destek_yetkilisi",
}

CLOSED_ROLES = {
    "",
    "none",
    "null",
    "personel",
    "kullanici",
    "standart_kullanici",
    "standart_personel",
}


def _normalize(value: Any) -> str:
    raw = "" if value is None else str(value)
    raw = raw.strip().lower()
    raw = raw.replace("ı", "i").replace("İ", "i")
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9]+", "_", raw)
    return re.sub(r"_+", "_", raw).strip("_")


def _truthy(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text_value = str(value).strip().lower()
    if text_value in {"1", "true", "evet", "yes", "on", "acik", "açık", "enabled", "open"}:
        return True
    if text_value in {"0", "false", "hayir", "hayır", "no", "off", "kapali", "kapalı", "disabled", "closed"}:
        return False
    return None


def _current_role() -> str:
    user = current_user
    if not user or not getattr(user, "is_authenticated", False):
        return ""

    for attr in ("role", "role_label", "unvan"):
        value = getattr(user, attr, None)
        if value:
            return _normalize(value)
    return ""


def _db_session():
    try:
        from app.extensions import db
        return db.session
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=144")
        return None


# BYS360_SQLITE_POSTGRES_DB_COMPAT_V2_17_50
def _table_columns(session, table_name: str) -> set[str]:
    """Tablo kolonlarını DB motoruna göre güvenli okur.

    Not:
    - BYS360 DEFECT AL: PostgreSQL tarafı artık SQLAlchemy'nin dialect-neutral
      inspect() katmanını kullanır (aşağıdaki fallback bloğu); ayrı bir raw
      information_schema.columns dalı tutulmuyor.
    - SQLite local/test ortamında inspect() PRAGMA table_info üzerinden çalışır;
      inspect() beklenmedik şekilde başarısız olursa doğrudan PRAGMA'ya düşülür.
    - Hata logunu spamlememek için beklenen dialect uyumsuzlukları exception olarak loglanmaz.
    """
    if text is None or session is None:
        return set()

    table = str(table_name or "").strip()
    if not table or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        return set()

    bind = None
    dialect_name = ""
    try:
        bind = session.get_bind() if hasattr(session, "get_bind") else getattr(session, "bind", None)
        dialect_name = str(getattr(getattr(bind, "dialect", None), "name", "") or "").lower()
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=169")
        bind = None
        dialect_name = ""

    if dialect_name == "sqlite":
        try:
            rows = session.execute(text(f'PRAGMA table_info("{table}")')).fetchall()
            return {str(row[1]) for row in rows if len(row) > 1}
        except Exception:
            logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=177")
            return set()

    try:
        from sqlalchemy import inspect
        if bind is not None:
            return {str(col.get("name")) for col in inspect(bind).get_columns(table) if col.get("name")}
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=194")
        pass

    try:
        rows = session.execute(text(f'PRAGMA table_info("{table}")')).fetchall()
        return {str(row[1]) for row in rows if len(row) > 1}
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=200")
        return set()


def _candidate_keys() -> set[str]:
    from app.services.assistant_settings_service import assistant_feature_aliases

    keys = set(ASSISTANT_MASTER_KEYS)
    for k in list(ASSISTANT_MASTER_KEYS):
        nk = _normalize(k)
        keys.add(nk)
        keys.add(f"module_{nk}")
        keys.add(f"menu_{nk}")
        keys.add(f"role_matrix_{nk}")
    keys.update(ASSISTANT_SHORTCUT_KEYS)
    normalized = {_normalize(k) for k in keys if k}
    normalized.update(assistant_feature_aliases("assistant_module"))
    return normalized


def _master_permission_row(rows):
    from app.services.assistant_settings_service import (
        assistant_feature_aliases,
        assistant_feature_row_priority,
    )

    master_keys = assistant_feature_aliases("assistant_module")
    return min(rows, key=lambda item: (
        assistant_feature_row_priority(item.permission_key, item.source_type, "assistant_module") if str(item.permission_key).lower() in master_keys else 4,
        -item.id,
    ))


def _query_role_menu_defaults(session, role: str) -> bool | None:
    if text is None:
        return None

    cols = _table_columns(session, "role_menu_defaults")
    if not cols:
        return None

    role_cols = [c for c in ("role", "role_key", "role_name", "role_label") if c in cols]
    key_cols = [c for c in ("menu_key", "feature_key", "permission_key", "module_key", "key", "code") if c in cols]
    value_cols = [c for c in ("is_visible", "visible", "enabled", "is_enabled", "allowed", "value") if c in cols]
    if not role_cols or not key_cols or not value_cols:
        return None

    role_col, key_col, value_col = role_cols[0], key_cols[0], value_cols[0]
    roles = {_normalize(role), role, role.replace("_", " ")}
    keys = _candidate_keys()
    source = "source_type" if "source_type" in cols else "NULL"

    try:
        sql = text(f"""
            select id, {key_col} as permission_key, {value_col} as visible, {source} as source_type
            from role_menu_defaults
            where lower(cast({role_col} as text)) in :roles
              and lower(cast({key_col} as text)) in :keys
        """)
        sql = sql.bindparams(bindparam("roles", expanding=True), bindparam("keys", expanding=True))
        sql = sql.bindparams(bindparam("roles", expanding=True), bindparam("keys", expanding=True))
        rows = session.execute(sql, {"roles": tuple(roles), "keys": tuple(keys)}).all()
        if rows:
            row = _master_permission_row(rows)
            return _truthy(row.visible)
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=246")
        return None

    return None


def _query_user_menu_permissions(session) -> bool | None:
    if text is None:
        return None

    user = current_user
    user_id = getattr(user, "id", None)
    if not user_id:
        return None

    cols = _table_columns(session, "user_menu_permissions")
    if not cols:
        return None

    user_cols = [c for c in ("user_id", "personnel_id", "account_id") if c in cols]
    key_cols = [c for c in ("menu_key", "feature_key", "permission_key", "module_key", "key", "code") if c in cols]
    value_cols = [c for c in ("is_visible", "visible", "enabled", "is_enabled", "allowed", "value") if c in cols]
    if not user_cols or not key_cols or not value_cols:
        return None

    user_col, key_col, value_col = user_cols[0], key_cols[0], value_cols[0]
    keys = _candidate_keys()
    source = "source_type" if "source_type" in cols else "NULL"

    try:
        sql = text(f"""
            select id, {key_col} as permission_key, {value_col} as visible, {source} as source_type
            from user_menu_permissions
            where {user_col} = :uid
              and lower(cast({key_col} as text)) in :keys
        """)
        sql = sql.bindparams(bindparam("keys", expanding=True))
        sql = sql.bindparams(bindparam("keys", expanding=True))
        rows = session.execute(sql, {"uid": user_id, "keys": tuple(keys)}).all()
        if rows:
            return _truthy(_master_permission_row(rows).visible)
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=286")
        return None

    return None


def _parse_json(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=302")
        return None


def _lookup_json_policy(data: Any, role: str) -> bool | None:
    if data is None:
        return None

    roles = {_normalize(role), role, role.replace("_", " ")}
    keys = _candidate_keys()

    if isinstance(data, dict):
        for key in keys:
            val = data.get(key)
            if isinstance(val, dict):
                for role_key in roles:
                    t = _truthy(val.get(role_key))
                    if t is not None:
                        return t
            else:
                t = _truthy(val)
                if t is not None:
                    return t

        for role_key in roles:
            val = data.get(role_key)
            if isinstance(val, dict):
                for key in keys:
                    t = _truthy(val.get(key))
                    if t is not None:
                        return t
            else:
                t = _truthy(val)
                if t is not None:
                    return t

        for val in data.values():
            found = _lookup_json_policy(val, role)
            if found is not None:
                return found

    if isinstance(data, list):
        for item in data:
            found = _lookup_json_policy(item, role)
            if found is not None:
                return found

    return None


def _query_module_settings(session, role: str) -> bool | None:
    if text is None:
        return None

    for table_name in ("module_settings", "system_settings"):
        cols = _table_columns(session, table_name)
        if not cols:
            continue

        key_cols = [c for c in ("key", "setting_key", "name", "code") if c in cols]
        value_cols = [c for c in ("value", "setting_value", "json_value", "data", "payload") if c in cols]
        if not key_cols or not value_cols:
            continue

        key_col, value_col = key_cols[0], value_cols[0]
        try:
            rows = session.execute(text(f"""
                select {key_col}, {value_col}
                from {table_name}
                where lower(cast({key_col} as text)) like '%assistant%'
                   or lower(cast({key_col} as text)) like '%asistan%'
                   or lower(cast({key_col} as text)) like '%role_matrix%'
                   or lower(cast({key_col} as text)) like '%rol_matrisi%'
            """)).fetchall()
        except Exception:
            __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: except bloğu loglandı (app/services/assistant_module_access.py:340)")
            continue

        for _, raw in rows:
            found = _lookup_json_policy(_parse_json(raw), role)
            if found is not None:
                return found

    return None


def assistant_module_enabled_for_current_user() -> bool:
    role = _current_role()

    session = _db_session()
    if session is not None:
        value = _query_user_menu_permissions(session)
        if value is not None:
            return bool(value)

        value = _query_module_settings(session, role)
        if value is not None:
            return bool(value)

        value = _query_role_menu_defaults(session, role)
        if value is not None:
            return bool(value)

    if role in CLOSED_ROLES:
        return False
    # BYS360 DEFECT AQ: burada önceden, DB tabanlı hiçbir politika satırı
    # bulunamadığında ve rol OPEN_ROLES/CLOSED_ROLES kümelerinin tam üyesi
    # olmadığında, rol metninde "baskan"/"admin"/"koordinat"/"grup" gibi alt
    # dizeler geçiyorsa modül erişimi veriliyordu -- "Başkanlığı Uzmanı" gibi
    # sıradan bir unvan da bu şekilde erişim kazanıyordu. Kataloglanmamış/
    # tanınmayan her rol artık güvenli varsayılan olarak reddedilir (OPEN_
    # ROLES'un tam üyesi olmayan hiçbir şey erişim kazanmaz).
    return role in OPEN_ROLES


def assistant_shortcut_visible(feature_key: str | None = None) -> bool:
    return assistant_module_enabled_for_current_user()


def assistant_module_visibility_payload() -> dict[str, Any]:
    enabled = assistant_module_enabled_for_current_user()
    return {
        "enabled": bool(enabled),
        "labels": list(ASSISTANT_TEXT_LABELS),
        "path_keywords": list(ASSISTANT_PATH_KEYWORDS),
    }


def _is_assistant_path() -> bool:
    if request is None:
        return False
    path = (request.path or "").lower()
    return any(keyword in path for keyword in ASSISTANT_PATH_KEYWORDS)


def register_assistant_module_master_access(app):
    """Sanal Asistan ana görünürlük helper'larını Flask context'ine güvenli bağlar.

    v58: Test ortamında context processor register edilmediğinde base.html 500 üretiyordu.
    Bu kayıt idempotent çalışır; aynı uygulama factory içinde iki kez çağrılsa bile
    tekrar context_processor/before_request eklemez.
    """
    if getattr(app, "_bys360_assistant_module_master_access_registered", False):
        return app

    @app.context_processor
    def _assistant_module_master_context():
        try:
            payload = assistant_module_visibility_payload()
        except Exception:
            logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=449")
            payload = {
                "enabled": False,
                "visible": False,
                "modules": {},
                "shortcuts": {},
                "reason": "safe_fallback",
            }
        return {
            "assistant_module_enabled_for_current_user": assistant_module_enabled_for_current_user,
            "assistant_shortcut_visible": assistant_shortcut_visible,
            "assistant_module_visibility_payload": assistant_module_visibility_payload,
            "assistant_module_visibility_payload_json": payload,
        }

    @app.before_request
    def _assistant_module_master_gate():
        if request is None:
            return None
        if not _is_assistant_path():
            return None

        user = current_user
        if not user or not getattr(user, "is_authenticated", False):
            return None

        if assistant_module_enabled_for_current_user():
            return None

        try:
            return redirect(url_for("main.dashboard"))
        except Exception:
            logger.exception("BYS360 V6B guarded exception | file=app/services/assistant_module_access.py | line=480")
            return abort(403)

    app._bys360_assistant_module_master_access_registered = True
    return app

# Compatibility guard.
