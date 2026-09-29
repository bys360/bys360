from __future__ import annotations

import json
import os
import secrets
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text

PACKAGE = "BYS360_PHASE2_MOBILE_ROLE_TOKEN_MATRIX_GATE_V1"
REPORT_REL = Path("reports/architecture/BYS360_PHASE2_MOBILE_ROLE_TOKEN_MATRIX_GATE_V1_REPORT.json")

ROLE_MATRIX_ENDPOINTS: list[dict[str, Any]] = [
    {"name": "me", "method": "GET", "path": "/api/mobile/me", "must_success": True},
    {"name": "dashboard_summary", "method": "GET", "path": "/api/mobile/dashboard/summary", "must_success": False},
    {"name": "push_status", "method": "GET", "path": "/api/mobile/push/status", "must_success": False},
    {"name": "personnel_list", "method": "GET", "path": "/api/mobile/personnel/list", "must_success": False},
    {"name": "personnel_all", "method": "GET", "path": "/api/mobile/personnel/all", "must_success": False},
]


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


def _create_user(db: Any, User: Any, *, role: str, role_label: str, password: str) -> Any:
    suffix = uuid4().hex[:10]
    sicil_no = f"TST2D{role[:3].upper()}{suffix}"
    email = f"phase2d-{role}-{suffix}@example.test"

    User.query.filter((User.sicil_no == sicil_no) | (User.email == email)).delete(synchronize_session=False)
    db.session.commit()

    user = User()
    columns = set(user.__table__.columns.keys())

    _set_if_column(user, columns, "sicil_no", sicil_no)
    _set_if_column(user, columns, "email", email)
    _set_if_column(user, columns, "ad", "Faz")
    _set_if_column(user, columns, "soyad", f"IkiD {role}")
    _set_if_column(user, columns, "full_name_cache", f"Faz IkiD {role} Test Kullanıcısı")
    _set_if_column(user, columns, "unvan", "Test Personeli")
    _set_if_column(user, columns, "birim", "Test Birimi")
    _set_if_column(user, columns, "ust_birim", "Test Üst Birimi")
    _set_if_column(user, columns, "role", role)
    _set_if_column(user, columns, "role_label", role_label)
    _set_if_column(user, columns, "is_active", True)
    _set_if_column(user, columns, "force_password_change", False)

    if hasattr(user, "set_password") and callable(user.set_password):
        user.set_password(password)
    elif "password_hash" in columns:
        from werkzeug.security import generate_password_hash
        user.password_hash = generate_password_hash(password)

    _fill_required_defaults(user)

    db.session.add(user)
    db.session.commit()
    return user


def _cleanup_users(db: Any, User: Any, identities: list[dict[str, Any]]) -> None:
    try:
        for item in identities:
            user_id = item.get("id")
            if user_id:
                found = db.session.get(User, int(user_id))
                if found is not None:
                    db.session.delete(found)
        db.session.commit()

        from sqlalchemy import or_
        filters = []
        for item in identities:
            if item.get("sicil_no"):
                filters.append(User.sicil_no == item["sicil_no"])
            if item.get("email"):
                filters.append(User.email == item["email"])
        if filters:
            User.query.filter(or_(*filters)).delete(synchronize_session=False)
            db.session.commit()
    except Exception:
        db.session.rollback()


def _login(client: Any, sicil_no: str, password: str) -> dict[str, Any]:
    response = client.post(
        "/api/mobile/auth/login",
        json={"username": sicil_no, "password": password},
    )
    payload = _json(response)
    return {
        "status_code": int(response.status_code),
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "user": payload.get("user") or {},
        "ok": int(response.status_code) == 200 and bool(payload.get("access_token")),
    }


def _call(client: Any, method: str, path: str, token: str | None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if method == "GET":
        response = client.get(path, headers=headers)
    elif method == "POST":
        response = client.post(path, json={"_bys360_quality_gate": True}, headers=headers)
    else:
        raise ValueError(f"Desteklenmeyen method: {method}")

    payload = _json(response)
    status_code = int(response.status_code)
    return {
        "method": method,
        "path": path,
        "status_code": status_code,
        "no_route_break": status_code not in {404, 405},
        "no_server_error": status_code < 500,
        "source": payload.get("source"),
        "has_items": bool(payload.get("items")),
        "payload_keys": sorted(payload.keys())[:20],
    }


def run_checks(root: Path, write_report: bool = True) -> dict[str, Any]:
    os.environ.setdefault("FLASK_ENV", "testing")
    os.environ.setdefault("APP_ENV", "testing")
    os.environ.setdefault("BYS360_TESTING", "1")
    os.environ.setdefault("BYS360_DISABLE_SCHEDULERS", "1")
    os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
    os.environ.setdefault("SECRET_KEY", "bys360-test-secret-key-for-quality-gates")
    os.environ.setdefault("JWT_SECRET_KEY", "bys360-test-jwt-secret-key-for-quality-gates")
    os.environ.setdefault("WTF_CSRF_ENABLED", "False")

    from app import create_app
    from app.extensions import db
    from app.models import User
    from app.services import runtime_schema

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    password = secrets.token_urlsafe(24)

    result: dict[str, Any] = {
        "package": PACKAGE,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "role_token_matrix_ok": False,
        "login_ok": False,
        "role_identity_ok": False,
        "matrix_route_ok": False,
        "users": {},
        "responses": [],
        "failures": [],
    }

    identities: list[dict[str, Any]] = []

    with app.app_context():
        db.create_all()
        runtime_schema.provision_all()  # raw-SQL tables production already has

        personel = _create_user(db, User, role="personel", role_label="Personel", password=password)
        admin = _create_user(db, User, role="admin", role_label="Sistem Yöneticisi", password=password)

        identities = [
            {"id": getattr(personel, "id", None), "sicil_no": getattr(personel, "sicil_no", None), "email": getattr(personel, "email", None)},
            {"id": getattr(admin, "id", None), "sicil_no": getattr(admin, "sicil_no", None), "email": getattr(admin, "email", None)},
        ]

        client = app.test_client()

        try:
            personel_login = _login(client, personel.sicil_no, password)
            admin_login = _login(client, admin.sicil_no, password)

            result["login_ok"] = bool(personel_login["ok"] and admin_login["ok"])
            result["users"] = {
                "personel": {
                    "login_status_code": personel_login["status_code"],
                    "has_access_token": bool(personel_login["access_token"]),
                    "response_role": personel_login["user"].get("role"),
                },
                "admin": {
                    "login_status_code": admin_login["status_code"],
                    "has_access_token": bool(admin_login["access_token"]),
                    "response_role": admin_login["user"].get("role"),
                },
            }

            result["role_identity_ok"] = (
                result["users"]["personel"]["response_role"] != result["users"]["admin"]["response_role"]
                and bool(result["users"]["personel"]["response_role"])
                and bool(result["users"]["admin"]["response_role"])
            )

            for role_name, login_result in (("personel", personel_login), ("admin", admin_login)):
                token = login_result["access_token"]
                for case in ROLE_MATRIX_ENDPOINTS:
                    item = _call(client, case["method"], case["path"], token)
                    item["role"] = role_name
                    item["name"] = case["name"]
                    item["must_success"] = bool(case["must_success"])

                    ok = item["no_route_break"] and item["no_server_error"]
                    if case["must_success"]:
                        ok = ok and item["status_code"] == 200

                    item["ok"] = ok
                    result["responses"].append(item)
                    if not ok:
                        result["failures"].append(item)

            result["matrix_route_ok"] = not result["failures"]
            result["role_token_matrix_ok"] = bool(
                result["login_ok"]
                and result["role_identity_ok"]
                and result["matrix_route_ok"]
            )

        finally:
            _cleanup_users(db, User, identities)

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
    return 0 if result["role_token_matrix_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
