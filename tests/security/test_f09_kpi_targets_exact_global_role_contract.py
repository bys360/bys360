"""Contract F09 (D2/D3): the institution-wide KPI target view comes from an exact stored role.

Approved policy (HUMAN_POLICY_APPROVED, 2026-10-10): ``grup_baskani`` gets no institution-wide KPI
view through text matching; ``role_label``, titles and free text are never an authority source;
web, mobile and API follow the same rule.

``app/services/sp1d_target_management_service._is_global_role`` treated every stored role that
merely CONTAINED "admin", "başkan" or "baskan" as global: ``grup_baskani`` ("grup_BASKANi") and
``super_admin`` listed, opened and edited every unit's KPI targets on /performans/stratejik/hedefler,
and the KPI dashboard (``sp1c_kpi_dashboard_service``, which reuses the helper) showed them all.
The mobile KPI API (``app.api.mobile.shared._has_global_scope``) already used an exact set.

Rule now: the web helper uses the same exact set as the mobile KPI API (admin, başkan, başkanlık,
başkan yardımcısı). Every other role sees and edits its own and its unit's targets, as before.
"""
from __future__ import annotations

import datetime
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

PASSWORD = "F09KpiExactGlobalRoleTest1!"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "f09_kpi_exact_global" / "dbs"
SAME_UNIT, OTHER_UNIT, OWNERLESS = "F09-AYNI-BIRIM-HEDEFI", "F09-DIGER-BIRIM-HEDEFI", "F09-KURUM-HEDEFI"

# sicil -> (role, role_label)
USERS = {
    "F9GRP": ("grup_baskani", None),
    "F9SUP": ("super_admin", None),
    "F9LBL": ("personel", "Grup Başkanı / Başkan"),
    "F9KOR": ("koordinator", None),
    "F9ADM": ("admin", None),
    "F9BSK": ("baskan", None),
    "F9BYR": ("baskan_yardimcisi", None),
}
SCOPED = ["F9GRP", "F9SUP", "F9LBL", "F9KOR"]
GLOBAL = ["F9ADM", "F9BSK", "F9BYR"]


@pytest.fixture
def app(monkeypatch):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    uri = "sqlite:///" + (_DB_ROOT / f"{uuid.uuid4().hex}.sqlite3").as_posix()
    for key, value in {
        "APP_ENV": "testing", "SECRET_KEY": "test-secret-key-f09-kpi-exact-global", "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1", "AUTO_REPAIR_SCHEMA": "false", "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false", "STRICT_ENV_VALIDATION": "false", "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false", "MAIL_SUPPRESS_SEND": "true", "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "f09-kpi-exact-global-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    from app.extensions import db
    from app.models import User
    from app.models.org_models import OrganizationUnit
    from app.modules.strategic_performance.models import PerformanceTarget

    with flask_app.app_context():
        db.create_all()
        units = {}
        for key in ("A", "B"):
            unit = OrganizationUnit(name=f"F09 Birim-{key}", unit_type="birim", is_active=True, sort_order=0)
            db.session.add(unit)
            db.session.flush()
            units[key] = unit.id
        users = {}
        for sicil, (role, label) in USERS.items():
            user = User(sicil_no=sicil, email=f"{sicil.lower()}@example.gov.tr", ad="Kpi", soyad=sicil, role=role,
                        role_label=label, birim="Birim-A", is_active=True, must_change_password=False,
                        must_set_security_question=False, organization_unit_id=units["A"])
            user.set_password(PASSWORD)
            db.session.add(user)
            users[sicil] = user
        db.session.flush()

        def _target(name, owner_unit_id):
            target = PerformanceTarget(
                target_code=f"F09-{uuid.uuid4().hex[:10]}", target_name=name, target_type="kurumsal", category="KPI",
                owner_user_id=None, owner_unit_id=owner_unit_id, weight=0, target_value=100, current_value=10,
                completion_rate=10, status="ongoing", risk_level="low", start_date=datetime.date(2026, 1, 1),
                end_date=datetime.date(2026, 12, 31))
            db.session.add(target)
            db.session.flush()
            return target.id

        flask_app.config["_F09"] = {
            "targets": {"same": _target(SAME_UNIT, units["A"]), "other": _target(OTHER_UNIT, units["B"]),
                        "ownerless": _target(OWNERLESS, None)},
            "ids": {sicil: user.id for sicil, user in users.items()},
        }
        db.session.commit()
    return flask_app


def _client(app, sicil):
    client = app.test_client()
    response = client.post("/login", data={"sicil_or_email": sicil, "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", ""), sicil
    return client


def _page(app, sicil, path):
    response = _client(app, sicil).get(path)
    assert response.status_code == 200, (sicil, path, response.status_code)
    return response.get_data(as_text=True)


@pytest.mark.parametrize("role,expected", [
    ("grup_baskani", False), ("grup_başkanı", False), ("super_admin", False), ("admin_sistem_yoneticisi", False),
    ("sistem_yoneticisi", False), ("baskanlik_uzmani", False), ("koordinator", False), ("personel", False),
    ("admin", True), ("baskan", True), ("başkan", True), ("baskanlik", True), ("baskan_yardimcisi", True),
    ("başkan_yardımcısı", True),
])
def test_only_an_exact_stored_role_is_global(role, expected):
    from app.services.sp1d_target_management_service import _is_global_role

    assert _is_global_role(SimpleNamespace(id=1, role=role, role_label="Başkan")) is expected


def test_web_and_mobile_share_the_same_global_set():
    from app.api.mobile.shared import _GLOBAL_ROLES
    from app.services.sp1d_target_management_service import _is_global_role

    for role in _GLOBAL_ROLES:
        assert _is_global_role(SimpleNamespace(id=1, role=role)) is True, role


@pytest.mark.parametrize("sicil", SCOPED)
def test_scoped_roles_list_only_their_units_targets(app, sicil):
    client = _client(app, sicil)
    for path in ("/performans/stratejik/hedefler", "/performans/stratejik/kpi-dashboard"):
        response = client.get(path)
        assert response.status_code in (200, 403), (sicil, path, response.status_code)
        body = response.get_data(as_text=True)
        assert OTHER_UNIT not in body and OWNERLESS not in body, (sicil, path)


@pytest.mark.parametrize("sicil", ["F9GRP", "F9KOR"])
def test_managers_keep_their_units_targets(app, sicil):
    assert SAME_UNIT in _page(app, sicil, "/performans/stratejik/hedefler")


@pytest.mark.parametrize("sicil", SCOPED)
def test_scoped_roles_cannot_open_or_edit_another_units_target(app, sicil):
    from app.extensions import db
    from app.models import User
    from app.services.sp1d_target_management_service import get_target_for_edit

    data = app.config["_F09"]
    with app.app_context():
        user = db.session.get(User, data["ids"][sicil])
        assert get_target_for_edit(data["targets"]["other"], user) is None
        assert get_target_for_edit(data["targets"]["same"], user) is not None
    other = data["targets"]["other"]
    _client(app, sicil).post(f"/performance/kpi/targets/{other}/edit", data={
        "target_code": "F09-INJECT", "target_name": "F09-INJECTED-NAME", "target_type": "kurumsal", "category": "kpi",
        "target_value": "100", "current_value": "99", "weight": "0"})
    from app.modules.strategic_performance.models import PerformanceTarget

    with app.app_context():
        row = db.session.get(PerformanceTarget, other)
        assert row is not None and row.target_name == OTHER_UNIT


@pytest.mark.parametrize("sicil", GLOBAL)
def test_admin_baskan_and_deputy_keep_the_institution_view(app, sicil):
    body = _page(app, sicil, "/performans/stratejik/hedefler")
    assert SAME_UNIT in body and OTHER_UNIT in body and OWNERLESS in body
