from __future__ import annotations

import json
import os
import secrets
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text

PACKAGE = "BYS360_PHASE2_AUTH_SUCCESS_FLOW_GATE_V1"
REPORT_REL = Path("reports/architecture/BYS360_PHASE2_AUTH_SUCCESS_FLOW_GATE_V1_REPORT.json")


def _json(response: Any) -> dict[str, Any]:
    try:
        return response.get_json(silent=True) or {}
    except Exception:
        return {}


def _set_if_column(user: Any, columns: set[str], name: str, value: Any) -> None:
    if name not in columns:
        return
    try:
        setattr(user, name, value)
    except AttributeError:
        # Bazı model alanları property olarak hesaplanır ve setter içermez.
        return


def _fill_required_defaults(user: Any) -> None:
    columns = set(user.__table__.columns.keys())

    for column in user.__table__.columns:
        if column.primary_key or column.nullable:
            continue
        if column.default is not None or column.server_default is not None:
            continue

        name = column.name
        current = getattr(user, name, None)
        if current not in (None, ""):
            continue

        col_type = column.type
        if isinstance(col_type, (String, Text)):
            _set_if_column(user, columns, name, f"test-{name}")
        elif isinstance(col_type, Boolean):
            _set_if_column(user, columns, name, False)
        elif isinstance(col_type, Integer):
            _set_if_column(user, columns, name, 0)
        elif isinstance(col_type, Float):
            _set_if_column(user, columns, name, 0.0)
        elif isinstance(col_type, DateTime):
            _set_if_column(user, columns, name, datetime.utcnow())
        elif isinstance(col_type, Date):
            _set_if_column(user, columns, name, date.today())


def _create_test_user(db: Any, User: Any, password: str) -> Any:
    suffix = uuid4().hex[:10]
    sicil_no = f"TST2C{suffix}"
    email = f"phase2c-{suffix}@example.test"

    # Önce aynı test kimliği kalmışsa temizle.
    User.query.filter((User.sicil_no == sicil_no) | (User.email == email)).delete(synchronize_session=False)
    db.session.commit()

    user = User()
    columns = set(user.__table__.columns.keys())

    _set_if_column(user, columns, "sicil_no", sicil_no)
    _set_if_column(user, columns, "email", email)
    _set_if_column(user, columns, "ad", "Faz")
    _set_if_column(user, columns, "soyad", "IkiC")
    _set_if_column(user, columns, "full_name_cache", "Faz IkiC Test Kullanıcısı")
    _set_if_column(user, columns, "unvan", "Test Personeli")
    _set_if_column(user, columns, "birim", "Test Birimi")
    _set_if_column(user, columns, "ust_birim", "Test Üst Birimi")
    _set_if_column(user, columns, "role", "personel")
    _set_if_column(user, columns, "role_label", "Personel")
    _set_if_column(user, columns, "is_active", True)
    _set_if_column(user, columns, "force_password_change", False)
    # A completed account: the forced first-login steps are done (the model defaults leave
    # both open, and the mobile API refuses such accounts: F-08).
    _set_if_column(user, columns, "must_change_password", False)
    _set_if_column(user, columns, "must_set_security_question", False)

    if hasattr(user, "set_password") and callable(user.set_password):
        user.set_password(password)
    elif "password_hash" in columns:
        from werkzeug.security import generate_password_hash
        user.password_hash = generate_password_hash(password)

    _fill_required_defaults(user)

    db.session.add(user)
    db.session.commit()
    return user


def _cleanup_user(db: Any, User: Any, user_id: int | None, sicil_no: str | None, email: str | None) -> None:
    try:
        query = User.query
        if user_id:
            found = db.session.get(User, user_id)
            if found is not None:
                db.session.delete(found)
                db.session.commit()
                return

        filters = []
        if sicil_no:
            filters.append(User.sicil_no == sicil_no)
        if email:
            filters.append(User.email == email)

        if filters:
            from sqlalchemy import or_
            query.filter(or_(*filters)).delete(synchronize_session=False)
            db.session.commit()
    except Exception:
        db.session.rollback()


def run_checks(root: Path, write_report: bool = True) -> dict[str, Any]:
    os.environ.setdefault("FLASK_ENV", "testing")
    os.environ.setdefault("BYS360_TESTING", "1")

    from app import create_app
    from app.extensions import db
    from app.models import User

    app = create_app()
    password = secrets.token_urlsafe(24)

    result: dict[str, Any] = {
        "package": PACKAGE,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "auth_success_flow_ok": False,
        "steps": [],
    }

    user_id: int | None = None
    sicil_no: str | None = None
    email: str | None = None

    with app.app_context():
        # SQLite/test ortamında tablo yoksa güvenli şekilde oluşturur.
        db.create_all()

        user = _create_test_user(db, User, password)
        user_id = int(getattr(user, "id", 0) or 0)
        sicil_no = getattr(user, "sicil_no", None)
        email = getattr(user, "email", None)

        client = app.test_client()

        try:
            login_response = client.post(
                "/api/mobile/auth/login",
                json={"username": sicil_no, "password": password},
            )
            login_json = _json(login_response)
            access_token = login_json.get("access_token")
            refresh_token = login_json.get("refresh_token")

            result["steps"].append({
                "name": "login_with_sicil",
                "status_code": int(login_response.status_code),
                "has_access_token": bool(access_token),
                "has_refresh_token": bool(refresh_token),
                "ok": int(login_response.status_code) == 200 and bool(access_token) and bool(refresh_token),
            })

            me_response = client.get(
                "/api/mobile/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            me_json = _json(me_response)

            result["steps"].append({
                "name": "me_with_access_token",
                "status_code": int(me_response.status_code),
                "source": me_json.get("source"),
                "has_items": bool(me_json.get("items")),
                "ok": int(me_response.status_code) == 200,
            })

            refresh_response = client.post(
                "/api/mobile/auth/refresh",
                json={"refresh_token": refresh_token},
            )
            refresh_json = _json(refresh_response)

            result["steps"].append({
                "name": "refresh_with_refresh_token",
                "status_code": int(refresh_response.status_code),
                "has_access_token": bool(refresh_json.get("access_token")),
                "has_refresh_token": bool(refresh_json.get("refresh_token")),
                "ok": int(refresh_response.status_code) == 200 and bool(refresh_json.get("access_token")),
            })

            result["auth_success_flow_ok"] = all(step["ok"] for step in result["steps"])

        finally:
            _cleanup_user(db, User, user_id, sicil_no, email)

    if write_report:
        report = root / REPORT_REL
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["report"] = str(report)

    return result


def main() -> int:
    root = Path.cwd()
    result = run_checks(root, write_report=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["auth_success_flow_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
