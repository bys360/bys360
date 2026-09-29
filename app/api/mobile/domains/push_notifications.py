from __future__ import annotations

from sqlalchemy import text

from app.api.mobile import mobile_api_bp
from app.api.mobile.shared import jsonify, request, require_mobile_user
from app.extensions import db
from app.services import runtime_schema


def _push_text(value, *, limit=500):
    text_value = str(value or "").strip()
    if not text_value or text_value.lower() in {"none", "null", "undefined"}:
        return ""
    return text_value[:limit]


def _is_sqlite() -> bool:
    # BYS360 DEFECT AR: db.session.bind is always None on this Flask-SQLAlchemy
    # runtime, so the previous db.session.bind.dialect.name lookup always raised
    # AttributeError and the swallowed exception made this always return False --
    # meaning SQLite always took the PostgreSQL SERIAL branch below, leaving
    # mobile_push_tokens.id permanently NULL (same root cause already fixed in
    # interim_notes_runtime.py::_dialect_name()).
    try:
        return db.session.get_bind().dialect.name == "sqlite"
    except Exception:
        return False


def provision_mobile_push_token_table() -> None:
    """Create the push token table (explicit maintenance only: flask runtime-schema provision)."""
    if _is_sqlite():
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS mobile_push_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token VARCHAR(512) NOT NULL,
                platform VARCHAR(30),
                device_id VARCHAR(120),
                app_version VARCHAR(60),
                device_label VARCHAR(180),
                is_active BOOLEAN NOT NULL DEFAULT 1,
                last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
    else:
        db.session.execute(text("""
            CREATE TABLE IF NOT EXISTS mobile_push_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                token VARCHAR(512) NOT NULL,
                platform VARCHAR(30),
                device_id VARCHAR(120),
                app_version VARCHAR(60),
                device_label VARCHAR(180),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                last_seen_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """))

    db.session.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_mobile_push_tokens_token
        ON mobile_push_tokens (token)
    """))

    db.session.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_mobile_push_tokens_user_active
        ON mobile_push_tokens (user_id, is_active)
    """))
    db.session.commit()


# Owned by Alembic revision b704bd9d68c0 (same columns and indexes).
MOBILE_PUSH_TOKENS_SCHEMA = runtime_schema.register(runtime_schema.SchemaGroup(
    name="mobile.push_tokens",
    tables=("mobile_push_tokens",),
    indexes=(
        ("mobile_push_tokens", "ix_mobile_push_tokens_token"),
        ("mobile_push_tokens", "ix_mobile_push_tokens_user_active"),
    ),
    columns=(
        ("mobile_push_tokens", "user_id"),
        ("mobile_push_tokens", "token"),
        ("mobile_push_tokens", "platform"),
        ("mobile_push_tokens", "device_id"),
        ("mobile_push_tokens", "app_version"),
        ("mobile_push_tokens", "device_label"),
        ("mobile_push_tokens", "is_active"),
        ("mobile_push_tokens", "last_seen_at"),
        ("mobile_push_tokens", "created_at"),
        ("mobile_push_tokens", "updated_at"),
    ),
    provision=provision_mobile_push_token_table,
))


def _ensure_mobile_push_token_table() -> None:
    """Verify the push token table exists; never creates it."""
    runtime_schema.require(MOBILE_PUSH_TOKENS_SCHEMA)


def _register_push_token_impl(user):
    payload = request.get_json(silent=True) or {}

    token = _push_text(payload.get("token"), limit=512)
    if not token:
        return jsonify({"ok": False, "error": "token_required"}), 400

    platform = _push_text(payload.get("platform"), limit=30) or "android"
    device_id = _push_text(payload.get("device_id"), limit=120)
    app_version = _push_text(payload.get("app_version"), limit=60)
    device_label = _push_text(payload.get("device_label"), limit=180)

    _ensure_mobile_push_token_table()

    existing = db.session.execute(
        text("""
            SELECT id
            FROM mobile_push_tokens
            WHERE token = :token
            LIMIT 1
        """),
        {"token": token},
    ).mappings().first()

    params = {
        "user_id": int(user.id),
        "token": token,
        "platform": platform,
        "device_id": device_id or None,
        "app_version": app_version or None,
        "device_label": device_label or None,
    }

    if existing:
        db.session.execute(
            text("""
                UPDATE mobile_push_tokens
                SET user_id = :user_id,
                    platform = :platform,
                    device_id = :device_id,
                    app_version = :app_version,
                    device_label = :device_label,
                    is_active = TRUE,
                    last_seen_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE token = :token
            """),
            params,
        )
        action = "updated"
    else:
        db.session.execute(
            text("""
                INSERT INTO mobile_push_tokens
                    (user_id, token, platform, device_id, app_version, device_label, is_active, last_seen_at, created_at, updated_at)
                VALUES
                    (:user_id, :token, :platform, :device_id, :app_version, :device_label, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            params,
        )
        action = "created"

    db.session.commit()

    return jsonify({
        "ok": True,
        "action": action,
        "push_enabled": True,
        "platform": platform,
    })


@mobile_api_bp.post("/push/register-token")
@require_mobile_user
def mobile_push_register_token(user):
    return _register_push_token_impl(user)


@mobile_api_bp.post("/notifications/fcm-token")
@require_mobile_user
def mobile_push_register_token_legacy_alias(user):
    return _register_push_token_impl(user)


@mobile_api_bp.post("/push/unregister-token")
@require_mobile_user
def mobile_push_unregister_token(user):
    payload = request.get_json(silent=True) or {}
    token = _push_text(payload.get("token"), limit=512)

    if not token:
        return jsonify({"ok": False, "error": "token_required"}), 400

    _ensure_mobile_push_token_table()

    db.session.execute(
        text("""
            UPDATE mobile_push_tokens
            SET is_active = FALSE,
                updated_at = CURRENT_TIMESTAMP
            WHERE token = :token
              AND user_id = :user_id
        """),
        {
            "token": token,
            "user_id": int(user.id),
        },
    )
    db.session.commit()

    return jsonify({"ok": True, "push_enabled": False})


@mobile_api_bp.get("/push/status")
@require_mobile_user
def mobile_push_status(user):
    _ensure_mobile_push_token_table()

    count = db.session.execute(
        text("""
            SELECT COUNT(*) AS total
            FROM mobile_push_tokens
            WHERE user_id = :user_id
              AND is_active = TRUE
        """),
        {"user_id": int(user.id)},
    ).scalar() or 0

    return jsonify({
        "ok": True,
        "active_tokens": int(count),
        "push_ready": int(count) > 0,
    })
