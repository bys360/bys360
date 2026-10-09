"""B1-F1 contract: scoped personnel directory and performance access (least privilege).

Approved policy (human decision B1-F1, 2026-10-09)
--------------------------------------------------
No role reads the whole personnel directory or other people's performance data just
because of its name. ``ik``, ``personel_yonetimi`` and ``performans_yetkilisi`` (and the
role_label spellings ``insan kaynaklari`` / ``insan kaynakları`` / ``personel yönetimi
yetkilisi``) lose the institution-wide shortcuts they had on mobile, on the web KPI target
screens and in the historical scorecard archive. They fall back to their scoped branches:
self, evaluator of an assignment, owner (user or unit) of a KPI target.

A central HR user may still list the whole directory, but only through an explicit,
role-independent, audited per-user grant: a ``user_menu_permissions`` row with
``menu_key="personnel_read_all"``, ``is_visible=True`` and ``source_type="user_override"``
on an active user. Only the admin-only per-user matrix on ``/settings``
(``form_action=save_user_visibility`` or its alias ``save_personnel_feature_matrix_full``)
saved by an admin for ANOTHER user creates or removes it, and that save writes a
``settings_change_logs`` row. Self-grant, bulk profiles, role/unit profiles, template
import, named archives and rollback never create an active grant. The grant opens only the
directory read; it never opens performance data, personnel creation, KPI writes or
private support tickets.

Contract (every check goes through a real HTTP route: mobile bearer tokens issued by
``app.api.mobile.shared._issue_token``; web sessions through ``POST /login``. The only
helper-level call is one check of ``has_personnel_read_all_grant`` for an inactive user,
whose token the mobile API refuses before any route code runs)
------------------------------------------------------------------------------------------
C1 The mobile global roles exclude ik, personel_yonetimi and performans_yetkilisi
   (as role and as role_label).
C2 GET /api/mobile/personnel/list and /api/mobile/personnel/all are institution-wide only
   for the remaining global roles (admin, baskan, ...) or an active grant holder; anyone
   else gets exactly their own record. The grant does not depend on role/role_label;
   is_visible=False, a foreign source_type, role defaults, unit profiles and an inactive
   user do nothing.
C3 A grant holder (role personel or role ik) still cannot read others' scorecards, tasks,
   task details or in-period notes, cannot update others' KPI progress, cannot create
   personnel and cannot read others' private support tickets.
C4 POST /api/mobile/personnel/create and /personnel/add are refused (403, no user row) for
   ik, personel_yonetimi and the HR role_label spellings; admin keeps it (201).
C5 Web KPI targets (/performance/kpi/targets, /performance/kpi/targets/<id>/edit and the
   sp1c /performance/kpi/dashboard, all on the SP-1D scope): ik and performans_yetkilisi
   do not list, count, open or change another owner's target; admin and baskan are
   unchanged. personel_yonetimi never passes the route guard (403 before and after the
   fix). Note: the edit template reads target.name/target.code and posts name/code, while
   the SP-1D service row and update read target_name/target_code; the tests therefore
   check the rendered description and post the service's field names.
C6 Web archive (/performance/archive, /<id>, /new, /import): ik, personel_yonetimi and
   performans_yetkilisi see only their own history and cannot write; admin is unchanged.
C7 Grant assignment and removal only through the admin per-user /settings matrix, audited;
   self-grant, non-admin posts, bulk_apply_profile, save_role_profile, save_unit_profile,
   import_visibility_template, apply_named_archive and rollback never grant.
C8 The web personnel pages (/admin/users, /personnel) stay closed to ik,
   personel_yonetimi, performans_yetkilisi and to a grant holder.

Approved decisions (HUMAN_POLICY_APPROVED, 2026-10-09) and review findings
------------------------------------------------------------------------------------------
D1 personel_yonetimi: self only until a reliable unit relation exists (covered by C1-C8).
D2 sistem_yoneticisi / system_admin are technical roles: no mobile institution-wide
   branch, no mobile personnel creation, no web-global KPI targets, no archive manage-all,
   no AI decision-support global evaluation scope or archive detail of other people.
D3 role_label (display text) never grants scope or creation, also when role is empty.
D4 no web directory for grant holders (C8).
R02 only the admin role assigns or removes the grant; the rest of the admin family
   (baskan, grup_baskani, mali_musavir) cannot, and their saves leave a grant unchanged.
R03/R04 AI decision support: ik, performans_yetkilisi and the technical roles get neither
   other people's archived results nor institution-wide evaluation category groups.
R07 static guard: only the grant module and the guarded settings paths touch the key.

Labels: tests named ``test_guard_*`` or ``test_positive_*`` are regression/positive guards
that also pass on the pre-fix code (ac299e8). Every other test fails on the pre-fix code
(wrong status code, leaked or changed data, a grant that is not created or not honoured,
or the missing grant reader) and passes with the B1-F1 fix.
"""
from __future__ import annotations

import datetime
import io
import json
import re
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

PASSWORD = "B1F1ScopedAccessContract1!"
GRANT_KEY = "personnel_read_all"
_DB_ROOT = Path(tempfile.gettempdir()) / "bys360" / "b1f1_contract"

# key: (role, role_label, birim, organization unit key, is_active)
_USERS: dict[str, tuple[str, str | None, str, str | None, bool]] = {
    "admin": ("admin", None, "Birim-A", "A", True),
    "baskan": ("baskan", None, "Birim-C", None, True),
    "mali_musavir": ("mali_musavir", None, "Birim-C", None, True),
    "ik": ("ik", None, "Birim-B", "B", True),
    "pyon": ("personel_yonetimi", None, "Birim-B", "B", True),
    "pyet": ("performans_yetkilisi", None, "Birim-B", "B", True),
    "evaluatee": ("personel", None, "Birim-A", "A", True),
    "other": ("personel", None, "Birim-A", "A", True),
    "other_eval": ("birim_sorumlusu", None, "Birim-A", "A", True),
    "personel": ("personel", None, "Birim-A", "A", True),
    "holder": ("personel", None, "Birim-B", "B", True),
    "holder_ik": ("ik", None, "Birim-B", "B", True),
    "colleague_b": ("personel", None, "Birim-B", "B", True),
    "label_ik": ("personel", "ik", "Birim-B", "B", True),
    "label_pyon": ("personel", "personel_yonetimi", "Birim-B", "B", True),
    "label_pyet": ("personel", "performans_yetkilisi", "Birim-B", "B", True),
    "label_hr_ascii": ("personel", "insan kaynaklari", "Birim-B", "B", True),
    "label_hr_tr": ("personel", "insan kaynakları", "Birim-B", "B", True),
    "label_pyon_title": ("personel", "personel yönetimi yetkilisi", "Birim-B", "B", True),
    "inactive_holder": ("personel", None, "Birim-B", "B", False),
    # Approved decisions 2 and 3 and review finding R02 (2026-10-09).
    "sysadm": ("sistem_yoneticisi", None, "Birim-B", "B", True),
    "sysadm_en": ("system_admin", None, "Birim-B", "B", True),
    "label_admin": ("personel", "admin", "Birim-B", "B", True),
    "label_baskan": ("personel", "baskan", "Birim-B", "B", True),
    "label_sysadm": ("personel", "sistem_yoneticisi", "Birim-B", "B", True),
    "label_only_admin": ("", "admin", "Birim-B", "B", True),
    "grup_baskani": ("grup_baskani", None, "Birim-C", None, True),
}
SICIL = {key: f"BF{index:02d}X" for index, key in enumerate(_USERS, start=1)}

DIRECTORY_PATHS = ("/api/mobile/personnel/list", "/api/mobile/personnel/all")
NOTES_V2 = "/api/mobile/performance/in-period-notes/v2"
# The sp1c KPI dashboard renders the scoped target count (its table reads item.name/item.code).
_DASHBOARD_TOTAL = re.compile(r"Toplam Hedef</span><strong>(\d+)</strong>")
KPI_OTHER = "CONTRACT-KPI-OTHER-OWNER"
KPI_UNIT_B = "CONTRACT-KPI-UNIT-B"
# The edit form renders target.description (it reads target.name/target.code, which the
# SP-1D row does not carry), so the edit-page checks use the description marker.
KPI_OTHER_DESC = "CONTRACT-KPI-OTHER-OWNER-DESCRIPTION"
KPI_UNIT_B_DESC = "CONTRACT-KPI-UNIT-B-DESCRIPTION"
ARCHIVE_OTHER = "CONTRACT-ARSIV-OTHER"
NOTE_OTHER = "CONTRACT-NOTE-ABOUT-OTHER"
TICKET_BODY = "CONTRACT-PRIVATE-TICKET-BODY"


# --------------------------------------------------------------------------------------
# App / synthetic data
# --------------------------------------------------------------------------------------


def _make_app(monkeypatch, uri):
    for key, value in {
        "APP_ENV": "testing",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "test-secret-key-b1f1-scoped-access-contract",
        "DATABASE_URL": uri,
        "FLASK_SKIP_SCHEMA_VALIDATION": "1",
        "AUTO_REPAIR_SCHEMA": "false",
        "STRICT_SCHEMA_CHECK": "false",
        "REQUIRE_DOTENV_FILE": "false",
        "STRICT_ENV_VALIDATION": "false",
        "WTF_CSRF_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "MAIL_SUPPRESS_SEND": "true",
        "LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER": "false",
        "DEFAULT_FIRST_LOGIN_PASSWORD": "b1f1-contract-first-login",
    }.items():
        monkeypatch.setenv(key, value)
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "APP_ENV", "testing")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", uri)
    monkeypatch.setattr(Config, "SQLALCHEMY_ENGINE_OPTIONS", {})
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI=uri)
    return flask_app


_HASH_CACHE: dict[str, str] = {}


def _password_hash() -> str:
    """One real User.set_password hash per process (hashing 20 users per test is slow)."""
    if "hash" not in _HASH_CACHE:
        from app.models import User

        probe = User()
        probe.set_password(PASSWORD)
        _HASH_CACHE["hash"] = probe.password_hash
    return _HASH_CACHE["hash"]


def _seed() -> SimpleNamespace:
    from app.extensions import db
    from app.models import (
        EvaluationAssignment,
        PerformancePeriod,
        PerformanceResultSnapshot,
        SupportTicket,
        User,
    )
    from app.models.org_models import OrganizationUnit
    from app.models.performance_archive_models import PerformanceArchivedResult
    from app.modules.strategic_performance.models import PerformanceTarget

    units: dict[str, int] = {}
    for key in ("A", "B"):
        unit = OrganizationUnit(name=f"Contract Birim-{key}", unit_type="birim", is_active=True, sort_order=0)
        db.session.add(unit)
        db.session.flush()
        units[key] = int(unit.id)

    ids: dict[str, int] = {}
    for key, (role, label, birim, unit_key, active) in _USERS.items():
        user = User(
            sicil_no=SICIL[key],
            email=f"{SICIL[key].lower()}@example.gov.tr",
            ad="Kisi",
            soyad=SICIL[key],
            role=role,
            role_label=label,
            birim=birim,
            is_active=active,
            must_change_password=False,
            must_set_security_question=False,
            is_first_login=False,
            organization_unit_id=units[unit_key] if unit_key else None,
        )
        user.password_hash = _password_hash()
        db.session.add(user)
        db.session.flush()
        ids[key] = int(user.id)

    period = PerformancePeriod(
        title="Contract Donem",
        name="Contract Donem",
        period_type="yillik",
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 12, 31),
        is_active=True,
    )
    db.session.add(period)
    db.session.flush()

    assignments = {}
    for name, evaluator, employee in (("evaluatee", "pyet", "evaluatee"), ("other", "other_eval", "other")):
        row = EvaluationAssignment(
            period_id=period.id,
            employee_id=ids[employee],
            evaluator_id=ids[evaluator],
            manager_level=1,
            status="bekliyor",
        )
        db.session.add(row)
        db.session.flush()
        assignments[name] = int(row.id)

    snapshots = {}
    for key in ("other", "evaluatee", "personel", "holder"):
        row = PerformanceResultSnapshot(
            period_id=period.id,
            employee_id=ids[key],
            employee_name_snapshot=f"Kisi {SICIL[key]}",
            sicil_no_snapshot=SICIL[key],
            final_total_100=82,
            published_at=datetime.datetime(2026, 6, 1, 9, 0, 0),
        )
        db.session.add(row)
        db.session.flush()
        snapshots[key] = int(row.id)

    targets = {}
    # "other": a personal target of another user with no owner unit (no same-unit match);
    # "unit_b": an ownerless target of Birim-B (the unit of ik / performans_yetkilisi).
    for name, title, description, owner_key, unit_key in (
        ("other", KPI_OTHER, KPI_OTHER_DESC, "other", None),
        ("unit_b", KPI_UNIT_B, KPI_UNIT_B_DESC, None, "B"),
    ):
        row = PerformanceTarget(
            target_code=f"CT-{name.upper()}-{uuid.uuid4().hex[:6]}",
            target_name=title,
            description=description,
            target_type="personnel",
            category="KPI",
            owner_user_id=ids[owner_key] if owner_key else None,
            owner_unit_id=units[unit_key] if unit_key else None,
            weight=0,
            target_value=100,
            current_value=10,
            completion_rate=10,
            status="ongoing",
            risk_level="low",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31),
        )
        db.session.add(row)
        db.session.flush()
        targets[name] = int(row.id)

    archives = {}
    for key, label in (
        ("other", ARCHIVE_OTHER),
        ("ik", f"CONTRACT-ARSIV-OWN-{SICIL['ik']}"),
        ("pyon", f"CONTRACT-ARSIV-OWN-{SICIL['pyon']}"),
        ("pyet", f"CONTRACT-ARSIV-OWN-{SICIL['pyet']}"),
        ("sysadm", f"CONTRACT-ARSIV-OWN-{SICIL['sysadm']}"),
        ("sysadm_en", f"CONTRACT-ARSIV-OWN-{SICIL['sysadm_en']}"),
    ):
        row = PerformanceArchivedResult(
            employee_id=ids[key],
            result_year=2024,
            period_label=label,
            score=Decimal("88.00"),
            description="Contract archive row",
            source_type="manual",
            created_by_user_id=ids["admin"],
        )
        db.session.add(row)
        db.session.flush()
        archives[key] = int(row.id)

    ticket = SupportTicket(
        ticket_no="CT-PRIV-1",
        title="Contract private ticket",
        description=TICKET_BODY,
        ticket_type="other",
        module_name="test",
        status="open",
        created_by_user_id=ids["colleague_b"],
        is_private=True,
        unit_name_snapshot="Birim-B",
    )
    db.session.add(ticket)
    db.session.flush()
    db.session.commit()
    return SimpleNamespace(
        ids=ids,
        units=units,
        period=int(period.id),
        assignments=assignments,
        snapshots=snapshots,
        targets=targets,
        archives=archives,
        ticket=int(ticket.id),
    )


@pytest.fixture
def env(monkeypatch, install_interim_notes_schema):
    from sqlalchemy import event

    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_file = _DB_ROOT / f"b1f1_{uuid.uuid4().hex}.sqlite3"
    app = _make_app(monkeypatch, "sqlite:///" + db_file.as_posix())
    from app.extensions import db
    from app.services import runtime_schema

    with app.app_context():
        engine = db.engine

        @event.listens_for(engine, "connect")
        def _fast_temp_sqlite(dbapi_connection, _record):  # throwaway test DB: no fsync
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA synchronous=OFF")
            cursor.execute("PRAGMA journal_mode=MEMORY")
            cursor.close()

        engine.dispose()
        db.create_all()
        runtime_schema.provision_all()
        install_interim_notes_schema(db.engine)
        data = _seed()
    data.app = app
    yield data
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    db_file.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------
# Request helpers
# --------------------------------------------------------------------------------------


def _headers(env, who):
    from app.api.mobile.shared import _issue_token
    from app.extensions import db
    from app.models import User

    with env.app.app_context():
        user = db.session.get(User, env.ids[who])
        assert user is not None
        return {"Authorization": f"Bearer {_issue_token(user)}"}


def _mget(env, who, path):
    return env.app.test_client().get(path, headers=_headers(env, who))


def _mpost(env, who, path, payload):
    return env.app.test_client().post(path, json=payload, headers=_headers(env, who))


def _web(env, who):
    client = env.app.test_client()
    response = client.post("/login", data={"sicil_or_email": SICIL[who], "password": PASSWORD})
    assert response.status_code == 302 and "/login" not in response.headers.get("Location", ""), who
    return client


def _text(response) -> str:
    return response.get_data(as_text=True)


def _leaked(text: str, *keys: str) -> list[str]:
    return [key for key in keys if SICIL[key] in text]


def _others(who: str) -> list[str]:
    return [key for key in _USERS if key != who]


def _item_ids(response) -> set[int]:
    return {int(item["id"]) for item in (response.get_json() or {}).get("items") or []}


def _assert_self_only(env, who, path):
    response = _mget(env, who, path)
    assert response.status_code == 200, (path, response.status_code)
    assert _item_ids(response) == {env.ids[who]}, f"{who} must see only its own record on {path}"
    assert _leaked(_text(response), *_others(who)) == [], f"{path} leaked other people to {who}"


def _assert_institution_wide(env, who, path):
    response = _mget(env, who, path)
    assert response.status_code == 200, (path, response.status_code)
    active = {env.ids[key] for key, spec in _USERS.items() if spec[4]}
    listed = _item_ids(response)
    assert active <= listed, f"{who} must see the whole active directory on {path}"
    assert env.ids["inactive_holder"] not in listed


def _seed_grant(env, who, *, is_visible=True, source_type="user_override"):
    from app.extensions import db
    from app.models import UserMenuPermission

    with env.app.app_context():
        row = UserMenuPermission.query.filter_by(user_id=env.ids[who], menu_key=GRANT_KEY).first()
        if row is None:
            row = UserMenuPermission(user_id=env.ids[who], menu_key=GRANT_KEY)
            db.session.add(row)
        row.is_visible = is_visible
        row.source_type = source_type
        db.session.commit()


def _grant_row(env, who):
    from app.models import UserMenuPermission

    with env.app.app_context():
        row = UserMenuPermission.query.filter_by(user_id=env.ids[who], menu_key=GRANT_KEY).first()
        return None if row is None else (bool(row.is_visible), row.source_type)


def _has_active_grant_row(env, who) -> bool:
    return _grant_row(env, who) == (True, "user_override")


def _change_logs(env, who):
    from app.models import SettingsChangeLog

    with env.app.app_context():
        rows = (
            SettingsChangeLog.query.filter_by(target_user_id=env.ids[who], change_scope="user_menu_overrides")
            .order_by(SettingsChangeLog.id.asc())
            .all()
        )
        return [
            SimpleNamespace(
                id=int(row.id),
                actor=row.actor_user_id,
                action=row.action_type,
                new_state=json.loads(row.new_state_json or "{}"),
            )
            for row in rows
        ]


def _settings(env, actor, data, client=None):
    client = client or _web(env, actor)
    return client.post("/settings", data=data)


def _grant_via_settings(env, target, *, actor="admin", form_action="save_user_visibility", client=None):
    data = {"form_action": form_action, "user_id": str(env.ids[target]), f"menu_{GRANT_KEY}": "on"}
    return _settings(env, actor, data, client=client)


def _save_matrix_without_grant(env, target, *, actor="admin", client=None):
    data = {"form_action": "save_user_visibility", "user_id": str(env.ids[target])}
    return _settings(env, actor, data, client=client)


def _target_state(env, key):
    from app.extensions import db
    from app.modules.strategic_performance.models import PerformanceTarget

    with env.app.app_context():
        row = db.session.get(PerformanceTarget, env.targets[key])
        assert row is not None
        return (row.target_name, float(row.current_value or 0), row.owner_user_id, row.owner_unit_id)


def _target_code(env, key) -> str:
    from app.extensions import db
    from app.modules.strategic_performance.models import PerformanceTarget

    with env.app.app_context():
        row = db.session.get(PerformanceTarget, env.targets[key])
        assert row is not None
        return str(row.target_code)


def _archive_count(env) -> int:
    from app.models.performance_archive_models import PerformanceArchivedResult

    with env.app.app_context():
        return PerformanceArchivedResult.query.count()


def _user_exists(env, sicil) -> bool:
    from app.models import User

    with env.app.app_context():
        return User.query.filter_by(sicil_no=sicil).first() is not None


def _note_count(env, employee_key) -> int:
    from sqlalchemy import text

    from app.extensions import db

    with env.app.app_context():
        row = db.session.execute(
            text("SELECT COUNT(*) FROM performance_interim_notes WHERE employee_id = :e"),
            {"e": env.ids[employee_key]},
        ).first()
        return int(row[0]) if row else 0


def _ticket_message_count(env) -> int:
    from app.models import SupportTicketMessage

    with env.app.app_context():
        return SupportTicketMessage.query.filter_by(ticket_id=env.ticket).count()


def _seed_note_about_other(env):
    # Real route: other_eval is the evaluator of "other", so the note is legitimately created.
    response = _mpost(env, "other_eval", NOTES_V2, {"employee_id": env.ids["other"], "note": NOTE_OTHER})
    assert response.status_code == 200, _text(response)


def _create_personnel(env, who, path="/api/mobile/personnel/create"):
    sicil = f"CTNEW{uuid.uuid4().hex[:6].upper()}"
    payload = {
        "sicil_no": sicil,
        "ad": "Yeni",
        "soyad": "Personel",
        "unvan": "Uzman",
        "birim": "Birim-B",
        "ust_birim": "Baskanlik",
        "yonetici_sicil": SICIL["admin"],
        "role": "personel",
    }
    return _mpost(env, who, path, payload), sicil


def _kpi_edit_form(env, key, name):
    return {
        "target_code": _target_code(env, key),
        "target_name": name,
        "target_type": "birim",
        "category": "kpi",
        "target_value": "100",
        "current_value": "55",
        "weight": "10",
    }


def _dashboard_total(client) -> int:
    response = client.get("/performance/kpi/dashboard")
    assert response.status_code == 200
    match = _DASHBOARD_TOTAL.search(_text(response))
    assert match is not None, "KPI dashboard total counter not rendered"
    return int(match.group(1))


def _archive_xlsx(sicil: str, label: str) -> io.BytesIO:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Sicil No", "Personel ID", "Personel", "Yıl", "Dönem", "Puan", "Açıklama", "Kaynak Belge"])
    sheet.append([sicil, None, None, 2023, label, 77, "Contract import", "contract.xlsx"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


# --------------------------------------------------------------------------------------
# C1/C2 + scenarios 1, 2, 6, 7: mobile directory scope
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["ik", "pyon", "pyet", "label_ik", "label_pyon", "label_pyet"])
def test_hr_and_performance_roles_are_not_mobile_global_directory_is_self_only(env, who):
    """C1/C2, scenarios 1 and 2: role or role_label ik / personel_yonetimi / performans_yetkilisi."""
    for path in DIRECTORY_PATHS:
        _assert_self_only(env, who, path)
    body = _mget(env, who, "/api/mobile/personnel/all").get_json()
    assert body["scope"] == "Kendi kaydım"
    assert body["can_create_personnel"] is False


@pytest.mark.parametrize("who", ["admin", "baskan"])
def test_positive_remaining_global_roles_keep_institution_wide_directory(env, who):
    for path in DIRECTORY_PATHS:
        _assert_institution_wide(env, who, path)


def test_grant_holder_gets_institution_wide_directory(env):
    """Scenario 7: an active user_override grant on a plain personel opens the directory."""
    _seed_grant(env, "holder")
    for path in DIRECTORY_PATHS:
        _assert_institution_wide(env, "holder", path)
    assert _mget(env, "holder", "/api/mobile/personnel/all").get_json()["scope"] == "Genel"


def test_positive_grant_is_role_independent_for_an_ik_holder(env):
    """Positive: the grant also works for role ik (ik alone is self-only, see C1 test)."""
    _seed_grant(env, "holder_ik")
    for path in DIRECTORY_PATHS:
        _assert_institution_wide(env, "holder_ik", path)


def test_guard_grant_row_requires_visible_user_override(env):
    """Guard: is_visible=False or a source_type other than user_override does nothing."""
    for is_visible, source_type in ((False, "user_override"), (True, "rollback"), (True, "role_default")):
        _seed_grant(env, "holder", is_visible=is_visible, source_type=source_type)
        for path in DIRECTORY_PATHS:
            _assert_self_only(env, "holder", path)


def test_guard_role_defaults_and_unit_profiles_never_grant_the_directory(env):
    """Guard: a role default / unit profile row carrying the key is not a grant."""
    from app.extensions import db
    from app.models import RoleMenuDefault, UnitMenuProfile

    with env.app.app_context():
        db.session.add(RoleMenuDefault(role_name="personel", menu_key=GRANT_KEY, is_visible=True, source_type="manual"))
        db.session.add(UnitMenuProfile(unit_name="Birim-B", menu_key=GRANT_KEY, is_visible=True, source_type="manual"))
        db.session.commit()
    for who in ("holder", "colleague_b"):
        for path in DIRECTORY_PATHS:
            _assert_self_only(env, who, path)


def test_inactive_grant_holder_gets_nothing(env):
    """C2: an inactive user's grant row does nothing (token refused; reader fails closed)."""
    from app.extensions import db
    from app.models import User

    _seed_grant(env, "inactive_holder")
    for path in DIRECTORY_PATHS:
        response = _mget(env, "inactive_holder", path)
        assert response.status_code == 401
        assert _leaked(_text(response), *_others("inactive_holder")) == []
    try:
        from app.services.personnel_read_grant import has_personnel_read_all_grant
    except ImportError:
        pytest.fail("B1-F1 grant reader app.services.personnel_read_grant.has_personnel_read_all_grant is missing")
    with env.app.app_context():
        user = db.session.get(User, env.ids["inactive_holder"])
        assert user is not None
        assert has_personnel_read_all_grant(user) is False
        user.is_active = True
        assert has_personnel_read_all_grant(user) is True, "same row must count once the user is active"
        db.session.rollback()


def test_guard_plain_personel_sees_only_own_data(env):
    """Scenario 6 (guard): directory, scorecards, tasks, KPI and notes stay self-scoped."""
    _seed_note_about_other(env)
    for path in DIRECTORY_PATHS:
        _assert_self_only(env, "personel", path)
    scorecards = _mget(env, "personel", "/api/mobile/performance/scorecards")
    assert scorecards.status_code == 200
    assert _item_ids(scorecards) == {env.snapshots["personel"]}
    tasks = _mget(env, "personel", "/api/mobile/performance/tasks")
    assert tasks.status_code == 200 and _item_ids(tasks) == set()
    detail = _mget(env, "personel", f"/api/mobile/performance/tasks/{env.assignments['other']}")
    assert detail.status_code == 403 and _leaked(_text(detail), "other", "other_eval") == []
    before = _target_state(env, "other")
    assert _mpost(env, "personel", f"/api/mobile/kpi/target-management/{env.targets['other']}/progress", {"current_value": 95}).status_code == 403
    assert _target_state(env, "other") == before
    notes = _mget(env, "personel", NOTES_V2)
    assert notes.status_code == 200 and NOTE_OTHER not in _text(notes)


# --------------------------------------------------------------------------------------
# C3 + scenario 8: the grant opens only the directory
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["holder", "holder_ik"])
def test_grant_holder_cannot_read_others_performance(env, who):
    _seed_grant(env, who)
    _seed_note_about_other(env)
    scorecards = _mget(env, who, "/api/mobile/performance/scorecards")
    assert scorecards.status_code == 200
    assert env.snapshots["other"] not in _item_ids(scorecards)
    assert _leaked(_text(scorecards), "other", "evaluatee", "personel") == []
    tasks = _mget(env, who, "/api/mobile/performance/tasks")
    assert tasks.status_code == 200
    assert _item_ids(tasks) == set()
    assert _leaked(_text(tasks), "other", "evaluatee") == []
    detail = _mget(env, who, f"/api/mobile/performance/tasks/{env.assignments['other']}")
    assert detail.status_code == 403
    assert _leaked(_text(detail), "other", "other_eval") == []
    notes = _mget(env, who, NOTES_V2)
    assert notes.status_code == 200
    assert NOTE_OTHER not in _text(notes)
    # Precondition: the grant is in effect, so the refusals above are not a missing-grant artifact.
    _assert_institution_wide(env, who, "/api/mobile/personnel/list")


@pytest.mark.parametrize("who", ["holder", "holder_ik"])
def test_grant_holder_cannot_write_kpi_progress_or_create_personnel(env, who):
    _seed_grant(env, who)
    before = _target_state(env, "other")
    response = _mpost(env, who, f"/api/mobile/kpi/target-management/{env.targets['other']}/progress", {"current_value": 95})
    assert response.status_code == 403
    assert _target_state(env, "other") == before
    for path in ("/api/mobile/personnel/create", "/api/mobile/personnel/add"):
        created, sicil = _create_personnel(env, who, path)
        assert created.status_code == 403, path
        assert not _user_exists(env, sicil)
    _assert_institution_wide(env, who, "/api/mobile/personnel/all")


@pytest.mark.parametrize("who", ["holder", "holder_ik"])
def test_grant_holder_cannot_read_or_answer_others_private_ticket(env, who):
    _seed_grant(env, who)
    detail = _mget(env, who, f"/api/mobile/support/tickets/{env.ticket}")
    assert detail.status_code == 403
    assert TICKET_BODY not in _text(detail)
    reply = _mpost(env, who, f"/api/mobile/support/tickets/{env.ticket}/reply", {"message": "Yetkisiz cevap"})
    assert reply.status_code == 403
    assert _ticket_message_count(env) == 0
    _assert_institution_wide(env, who, "/api/mobile/personnel/list")


# --------------------------------------------------------------------------------------
# C4: mobile personnel creation
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["ik", "pyon", "label_hr_ascii", "label_hr_tr", "label_pyon_title"])
def test_hr_roles_and_labels_cannot_create_personnel_on_mobile(env, who):
    for path in ("/api/mobile/personnel/create", "/api/mobile/personnel/add"):
        response, sicil = _create_personnel(env, who, path)
        assert response.status_code == 403, (who, path, response.status_code)
        assert not _user_exists(env, sicil)
        assert sicil not in _text(response)


def test_positive_admin_keeps_mobile_personnel_creation_and_kpi_progress(env):
    for path in ("/api/mobile/personnel/create", "/api/mobile/personnel/add"):
        response, sicil = _create_personnel(env, "admin", path)
        assert response.status_code == 201, path
        assert _user_exists(env, sicil)
    response = _mpost(env, "admin", f"/api/mobile/kpi/target-management/{env.targets['other']}/progress", {"current_value": 95})
    assert response.status_code == 200
    assert _target_state(env, "other")[1] == 95


# --------------------------------------------------------------------------------------
# Scenarios 3 and 4: performans_yetkilisi (evaluator scope only, IDOR by id)
# --------------------------------------------------------------------------------------


def test_performans_yetkilisi_task_list_shows_only_its_evaluatee(env):
    response = _mget(env, "pyet", "/api/mobile/performance/tasks")
    assert response.status_code == 200
    assert _item_ids(response) == {env.assignments["evaluatee"]}
    assert _leaked(_text(response), "other") == []


def test_performans_yetkilisi_task_detail_of_another_evaluator_is_refused(env):
    response = _mget(env, "pyet", f"/api/mobile/performance/tasks/{env.assignments['other']}")
    assert response.status_code == 403
    assert _leaked(_text(response), "other", "other_eval") == []


def test_positive_performans_yetkilisi_keeps_its_evaluatee_task(env):
    response = _mget(env, "pyet", f"/api/mobile/performance/tasks/{env.assignments['evaluatee']}")
    assert response.status_code == 200
    assert SICIL["evaluatee"] in _text(response)


def test_performans_yetkilisi_scorecards_hide_people_it_does_not_evaluate(env):
    response = _mget(env, "pyet", "/api/mobile/performance/scorecards")
    assert response.status_code == 200
    assert env.snapshots["other"] not in _item_ids(response)
    assert _leaked(_text(response), "other", "personel", "holder") == []


def test_performans_yetkilisi_cannot_update_another_owners_kpi_progress(env):
    before = _target_state(env, "other")
    response = _mpost(env, "pyet", f"/api/mobile/kpi/target-management/{env.targets['other']}/progress", {"current_value": 95})
    assert response.status_code == 403
    assert _target_state(env, "other") == before
    assert KPI_OTHER not in _text(response)


def test_performans_yetkilisi_cannot_note_a_non_evaluatee(env):
    before = _note_count(env, "other")
    response = _mpost(env, "pyet", NOTES_V2, {"employee_id": env.ids["other"], "note": "Yetkisiz not"})
    assert response.status_code == 403
    assert _note_count(env, "other") == before
    assert _leaked(_text(response), "other") == []


def test_positive_performans_yetkilisi_can_note_its_evaluatee(env):
    before = _note_count(env, "evaluatee")
    response = _mpost(env, "pyet", NOTES_V2, {"employee_id": env.ids["evaluatee"], "note": "Degerlendirilen notu"})
    assert response.status_code == 200
    assert _note_count(env, "evaluatee") == before + 1


def test_performans_yetkilisi_note_list_hides_notes_about_non_evaluatees(env):
    _seed_note_about_other(env)
    response = _mget(env, "pyet", NOTES_V2)
    assert response.status_code == 200
    assert NOTE_OTHER not in _text(response)
    assert _leaked(_text(response), "other") == []


# --------------------------------------------------------------------------------------
# C5 + scenario 5: web KPI targets and web/mobile parity
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["ik", "pyet"])
def test_web_kpi_target_list_hides_another_owners_target(env, who):
    response = _web(env, who).get("/performance/kpi/targets")
    assert response.status_code == 200
    assert KPI_OTHER not in _text(response)
    assert KPI_UNIT_B in _text(response), "the caller's own unit target stays listed"


@pytest.mark.parametrize("who", ["ik", "pyet"])
def test_web_kpi_target_edit_of_another_owners_target_is_refused(env, who):
    client = _web(env, who)
    url = f"/performance/kpi/targets/{env.targets['other']}/edit"
    page = client.get(url)
    assert page.status_code in {302, 403}, page.status_code
    assert KPI_OTHER not in _text(page) and KPI_OTHER_DESC not in _text(page)
    if page.status_code == 302:
        assert "/edit" not in page.headers.get("Location", "")
    before = _target_state(env, "other")
    posted = client.post(url, data=_kpi_edit_form(env, "other", "CONTRACT-KPI-HIJACKED"))
    assert posted.status_code in {302, 403}
    assert _target_state(env, "other") == before


@pytest.mark.parametrize("who", ["admin", "baskan"])
def test_positive_global_roles_keep_web_kpi_target_access(env, who):
    client = _web(env, who)
    listed = client.get("/performance/kpi/targets")
    assert listed.status_code == 200 and KPI_OTHER in _text(listed)
    url = f"/performance/kpi/targets/{env.targets['other']}/edit"
    page = client.get(url)
    assert page.status_code == 200 and KPI_OTHER_DESC in _text(page)
    assert _dashboard_total(client) == 2, "the KPI dashboard still counts every target"
    posted = client.post(url, data=_kpi_edit_form(env, "other", f"CONTRACT-KPI-EDITED-{who}"))
    assert posted.status_code == 302
    assert _target_state(env, "other")[0] == f"CONTRACT-KPI-EDITED-{who}"


@pytest.mark.parametrize("who", ["ik", "pyet"])
def test_web_kpi_dashboard_counts_only_own_scope_targets(env, who):
    """C5: the sp1c KPI dashboard shares the SP-1D scope; only the own-unit target counts."""
    assert _dashboard_total(_web(env, who)) == 1


def test_guard_personel_yonetimi_never_passes_the_web_kpi_route_guard(env):
    client = _web(env, "pyon")
    assert client.get("/performance/kpi/targets").status_code == 403
    page = client.get(f"/performance/kpi/targets/{env.targets['other']}/edit")
    assert page.status_code == 403 and KPI_OTHER_DESC not in _text(page)


def test_web_mobile_parity_directory_for_ik(env):
    """Scenario 5: the web personnel pages and the mobile directory agree for ik."""
    client = _web(env, "ik")
    for path in ("/personnel", "/admin/users"):
        page = client.get(path)
        assert page.status_code in {302, 403}
        assert _leaked(_text(page), "other", "personel") == []
    for path in DIRECTORY_PATHS:
        _assert_self_only(env, "ik", path)


def test_web_mobile_parity_kpi_edit_for_ik(env):
    """Scenario 5: same SP-1D rule on web edit and mobile progress (owner or own unit)."""
    client = _web(env, "ik")
    before = _target_state(env, "other")
    web_page = client.get(f"/performance/kpi/targets/{env.targets['other']}/edit")
    assert web_page.status_code in {302, 403} and KPI_OTHER_DESC not in _text(web_page)
    mobile = _mpost(env, "ik", f"/api/mobile/kpi/target-management/{env.targets['other']}/progress", {"current_value": 95})
    assert mobile.status_code == 403
    assert _target_state(env, "other") == before
    own_unit_page = client.get(f"/performance/kpi/targets/{env.targets['unit_b']}/edit")
    assert own_unit_page.status_code == 200 and KPI_UNIT_B_DESC in _text(own_unit_page)
    own_unit_mobile = _mpost(env, "ik", f"/api/mobile/kpi/target-management/{env.targets['unit_b']}/progress", {"current_value": 70})
    assert own_unit_mobile.status_code == 200
    assert _target_state(env, "unit_b")[1] == 70


# --------------------------------------------------------------------------------------
# C6: web performance archive
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["ik", "pyon", "pyet"])
def test_archive_read_is_own_history_only_for_hr_and_performance_roles(env, who):
    client = _web(env, who)
    listed = client.get("/performance/archive?no_cache=1")
    assert listed.status_code == 200
    assert ARCHIVE_OTHER not in _text(listed)
    assert _leaked(_text(listed), "other") == []
    assert f"CONTRACT-ARSIV-OWN-{SICIL[who]}" in _text(listed), "own history stays visible"
    detail = client.get(f"/performance/archive/{env.archives['other']}")
    assert detail.status_code == 403
    assert ARCHIVE_OTHER not in _text(detail)


@pytest.mark.parametrize("who", ["ik", "pyon", "pyet"])
def test_archive_write_is_refused_for_hr_and_performance_roles(env, who):
    client = _web(env, who)
    before = _archive_count(env)
    assert client.get("/performance/archive/new").status_code == 403
    assert client.get("/performance/archive/import").status_code == 403
    client.post(
        "/performance/archive/new",
        data={"employee_id": str(env.ids["other"]), "result_year": "2022", "period_label": "CONTRACT-NEW", "score": "91"},
    )
    client.post(
        "/performance/archive/import",
        data={"archive_excel": (_archive_xlsx(SICIL["other"], "CONTRACT-IMPORT"), "arsiv.xlsx")},
        content_type="multipart/form-data",
    )
    assert _archive_count(env) == before


def test_positive_admin_keeps_archive_read_and_write(env):
    client = _web(env, "admin")
    listed = client.get("/performance/archive?no_cache=1")
    assert listed.status_code == 200 and ARCHIVE_OTHER in _text(listed)
    detail = client.get(f"/performance/archive/{env.archives['other']}")
    assert detail.status_code == 200 and ARCHIVE_OTHER in _text(detail)
    assert client.get("/performance/archive/new").status_code == 200
    before = _archive_count(env)
    created = client.post(
        "/performance/archive/new",
        data={"employee_id": str(env.ids["other"]), "result_year": "2022", "period_label": "CONTRACT-NEW", "score": "91"},
    )
    assert created.status_code == 302
    imported = client.post(
        "/performance/archive/import",
        data={"archive_excel": (_archive_xlsx(SICIL["other"], "CONTRACT-IMPORT"), "arsiv.xlsx")},
        content_type="multipart/form-data",
    )
    assert imported.status_code == 200
    assert _archive_count(env) == before + 2


# --------------------------------------------------------------------------------------
# C7 + scenario 9: grant assignment, revocation and the paths that must never grant
# --------------------------------------------------------------------------------------


def test_admin_per_user_matrix_creates_an_active_audited_grant(env):
    response = _grant_via_settings(env, "holder")
    assert response.status_code == 302
    assert _grant_row(env, "holder") == (True, "user_override")
    logs = [log for log in _change_logs(env, "holder") if log.new_state.get(GRANT_KEY) is True]
    assert logs, "the grant save must write a settings_change_logs row naming the target"
    assert logs[-1].actor == env.ids["admin"]
    for path in DIRECTORY_PATHS:
        _assert_institution_wide(env, "holder", path)


def test_alias_save_personnel_feature_matrix_full_grants_another_user(env):
    _grant_via_settings(env, "holder", form_action="save_personnel_feature_matrix_full")
    assert _has_active_grant_row(env, "holder")
    _assert_institution_wide(env, "holder", "/api/mobile/personnel/list")


def test_revocation_returns_the_directory_to_self(env):
    """Scenario 9: a later admin save without the checkbox ends wide access."""
    client = _web(env, "admin")
    _grant_via_settings(env, "holder", client=client)
    assert _has_active_grant_row(env, "holder")
    _assert_institution_wide(env, "holder", "/api/mobile/personnel/list")
    assert _save_matrix_without_grant(env, "holder", client=client).status_code == 302
    assert not _has_active_grant_row(env, "holder")
    assert _change_logs(env, "holder")[-1].new_state.get(GRANT_KEY) is False
    for path in DIRECTORY_PATHS:
        _assert_self_only(env, "holder", path)


def test_rollback_of_the_revocation_never_restores_an_active_grant(env):
    client = _web(env, "admin")
    _grant_via_settings(env, "holder", client=client)
    assert _has_active_grant_row(env, "holder")
    _save_matrix_without_grant(env, "holder", client=client)
    revoke_log = _change_logs(env, "holder")[-1]
    response = _settings(
        env,
        "admin",
        {"form_action": "rollback_settings_change_entry", "change_log_id": str(revoke_log.id), "keep_user_id": str(env.ids["holder"])},
        client=client,
    )
    assert response.status_code == 302
    assert any(log.action == "rollback" for log in _change_logs(env, "holder")), "rollback must have run"
    assert not _has_active_grant_row(env, "holder")
    _assert_self_only(env, "holder", "/api/mobile/personnel/list")


@pytest.mark.parametrize("form_action", ["save_user_visibility", "save_personnel_feature_matrix_full", "contract_unknown_action"])
def test_guard_admin_family_self_grant_is_refused(env, form_action):
    """Guard: an admin-family user saving its OWN matrix never grants itself."""
    before = len(_change_logs(env, "mali_musavir"))
    _grant_via_settings(env, "mali_musavir", actor="mali_musavir", form_action=form_action)
    assert len(_change_logs(env, "mali_musavir")) == before + 1, "the self save must have run"
    assert not _has_active_grant_row(env, "mali_musavir")
    _assert_self_only(env, "mali_musavir", "/api/mobile/personnel/list")


def test_guard_unknown_form_action_never_grants_another_user(env):
    before = len(_change_logs(env, "holder"))
    _grant_via_settings(env, "holder", form_action="contract_unknown_action")
    assert len(_change_logs(env, "holder")) == before + 1
    assert not _has_active_grant_row(env, "holder")
    _assert_self_only(env, "holder", "/api/mobile/personnel/list")


@pytest.mark.parametrize("who", ["ik", "personel"])
def test_guard_non_admin_cannot_post_settings(env, who):
    for target in (who, "holder"):
        response = _grant_via_settings(env, target, actor=who)
        assert response.status_code == 403
        assert _grant_row(env, target) is None
        assert _change_logs(env, target) == []


def test_bulk_apply_profile_keeps_an_existing_grant_and_creates_none(env):
    from app.extensions import db
    from app.models import RoleMenuDefault

    with env.app.app_context():
        db.session.add(RoleMenuDefault(role_name="personel", menu_key=GRANT_KEY, is_visible=True, source_type="manual"))
        db.session.commit()
    _seed_grant(env, "holder")
    response = _settings(
        env,
        "admin",
        {"form_action": "bulk_apply_profile", "bulk_profile_key": "dynamic::role_defaults", "bulk_scope_type": "role", "bulk_role": "personel"},
    )
    assert response.status_code == 302
    assert "last_bulk_count" in response.headers.get("Location", ""), "bulk apply must have run"
    assert _grant_row(env, "holder") == (True, "user_override"), "bulk apply must leave the grant unchanged"
    for who in ("personel", "colleague_b", "evaluatee"):
        assert not _has_active_grant_row(env, who)
        _assert_self_only(env, who, "/api/mobile/personnel/list")
    _assert_institution_wide(env, "holder", "/api/mobile/personnel/list")


def test_guard_role_profile_save_never_grants(env):
    from app.models import RoleMenuDefault

    client = _web(env, "admin")
    response = _settings(
        env,
        "admin",
        {"form_action": "save_role_profile", "user_id": str(env.ids["personel"]), "profile_role_target": "personel", f"menu_{GRANT_KEY}": "on"},
        client=client,
    )
    assert response.status_code == 302
    with env.app.app_context():
        assert RoleMenuDefault.query.filter_by(role_name="personel", menu_key=GRANT_KEY, is_visible=True).count() == 0
    assert not _has_active_grant_row(env, "personel")
    _assert_self_only(env, "personel", "/api/mobile/personnel/list")
    _save_matrix_without_grant(env, "personel", client=client)
    assert not _has_active_grant_row(env, "personel")
    _assert_self_only(env, "personel", "/api/mobile/personnel/list")


def test_guard_unit_profile_save_never_grants(env):
    from app.models import UnitMenuProfile

    client = _web(env, "admin")
    response = _settings(
        env,
        "admin",
        {"form_action": "save_unit_profile", "user_id": str(env.ids["holder"]), "profile_unit_target": "Birim-B", f"menu_{GRANT_KEY}": "on"},
        client=client,
    )
    assert response.status_code == 302
    with env.app.app_context():
        assert UnitMenuProfile.query.filter_by(unit_name="Birim-B", menu_key=GRANT_KEY, is_visible=True).count() == 0
    for who in ("holder", "colleague_b"):
        assert not _has_active_grant_row(env, who)
        _assert_self_only(env, who, "/api/mobile/personnel/list")
    _save_matrix_without_grant(env, "holder", client=client)
    assert not _has_active_grant_row(env, "holder")
    _assert_self_only(env, "holder", "/api/mobile/personnel/list")


def test_guard_import_visibility_template_never_grants(env):
    template = json.dumps({"visible_keys": [GRANT_KEY], "effective_rule_map": {GRANT_KEY: True}})
    response = _settings(
        env,
        "admin",
        {"form_action": "import_visibility_template", "user_id": str(env.ids["holder"]), "import_template_json": template},
    )
    assert response.status_code == 302
    assert _change_logs(env, "holder"), "the template import must have saved the matrix"
    assert not _has_active_grant_row(env, "holder")
    _assert_self_only(env, "holder", "/api/mobile/personnel/list")


def test_guard_named_archive_apply_never_grants(env):
    from app.models import SystemSetting

    client = _web(env, "admin")
    saved = _settings(
        env,
        "admin",
        {
            "form_action": "save_named_archive",
            "user_id": str(env.ids["holder"]),
            "archive_name": "contract-arsiv",
            "archive_scope": "general",
            f"menu_{GRANT_KEY}": "on",
        },
        client=client,
    )
    assert saved.status_code == 302
    archive_key = "settings_archive::general::contract-arsiv"
    with env.app.app_context():
        assert SystemSetting.query.filter_by(setting_key=archive_key).count() == 1
    applied = _settings(
        env,
        "admin",
        {"form_action": "apply_named_archive", "user_id": str(env.ids["holder"]), "archive_key": archive_key, "archive_apply_mode": "user_override"},
        client=client,
    )
    assert applied.status_code == 302
    assert _change_logs(env, "holder"), "the archive must have been applied to the user"
    assert not _has_active_grant_row(env, "holder")
    _assert_self_only(env, "holder", "/api/mobile/personnel/list")


# --------------------------------------------------------------------------------------
# C8: web personnel pages are not widened
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["ik", "pyon", "pyet", "holder"])
def test_guard_web_personnel_pages_stay_closed(env, who):
    if who == "holder":
        _seed_grant(env, "holder")
    client = _web(env, who)
    for path in ("/admin/users", "/personnel"):
        page = client.get(path)
        assert page.status_code in {302, 403}, (path, page.status_code)
        if page.status_code == 302:
            location = page.headers.get("Location", "")
            assert "/admin/users" not in location and not location.rstrip("/").endswith("/personnel")
        assert _leaked(_text(page), "other", "personel", "evaluatee") == []


def test_guard_personel_yonetimi_cannot_change_personnel_on_web(env):
    from app.extensions import db
    from app.models import User

    client = _web(env, "pyon")
    response = client.post(
        f"/personnel/{env.ids['other']}/edit",
        data={"ad": "Degistirildi", "soyad": "Kisi", "sicil_no": SICIL["other"], "role": "admin"},
    )
    assert response.status_code == 403
    with env.app.app_context():
        user = db.session.get(User, env.ids["other"])
        assert user is not None
        assert (user.ad, user.role) == ("Kisi", "personel")


# --------------------------------------------------------------------------------------
# Approved decisions D2 (technical admin is not personal-data access) and D3 (role_label
# never grants), and review findings R02, R03, R04, R07
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["sysadm", "sysadm_en"])
def test_d2_technical_admin_roles_get_no_mobile_institution_wide_data(env, who):
    for path in DIRECTORY_PATHS:
        _assert_self_only(env, who, path)
    body = _mget(env, who, "/api/mobile/personnel/all").get_json()
    assert body["scope"] == "Kendi kaydım"
    assert body["can_create_personnel"] is False
    scorecards = _mget(env, who, "/api/mobile/performance/scorecards")
    assert scorecards.status_code == 200
    assert not (set(env.snapshots.values()) & _item_ids(scorecards))
    assert _leaked(_text(scorecards), "other", "evaluatee", "personel", "holder") == []
    tasks = _mget(env, who, "/api/mobile/performance/tasks")
    assert tasks.status_code == 200 and _item_ids(tasks) == set()
    assert _mget(env, who, f"/api/mobile/performance/tasks/{env.assignments['other']}").status_code == 403
    before = _target_state(env, "other")
    kpi = _mpost(env, who, f"/api/mobile/kpi/target-management/{env.targets['other']}/progress", {"current_value": 95})
    assert kpi.status_code == 403
    assert _target_state(env, "other") == before


@pytest.mark.parametrize("who", ["sysadm", "sysadm_en"])
def test_d2_technical_admin_roles_cannot_create_personnel_on_mobile(env, who):
    for path in ("/api/mobile/personnel/create", "/api/mobile/personnel/add"):
        response, sicil = _create_personnel(env, who, path)
        assert response.status_code == 403, (who, path, response.status_code)
        assert not _user_exists(env, sicil)


def test_d2_sistem_yoneticisi_is_not_web_global_on_kpi_targets(env):
    client = _web(env, "sysadm")
    listed = client.get("/performance/kpi/targets")
    assert listed.status_code == 200
    assert KPI_OTHER not in _text(listed)
    url = f"/performance/kpi/targets/{env.targets['other']}/edit"
    page = client.get(url)
    assert page.status_code in {302, 403, 404}
    assert KPI_OTHER_DESC not in _text(page)
    before = _target_state(env, "other")
    client.post(url, data=_kpi_edit_form(env, "other", "CONTRACT-KPI-HIJACKED-SYSADM"))
    assert _target_state(env, "other") == before


@pytest.mark.parametrize("who", ["sysadm", "sysadm_en"])
def test_d2_technical_admin_roles_see_only_own_archive_and_cannot_write(env, who):
    client = _web(env, who)
    listed = client.get("/performance/archive?no_cache=1")
    assert listed.status_code == 200
    assert ARCHIVE_OTHER not in _text(listed)
    assert f"CONTRACT-ARSIV-OWN-{SICIL[who]}" in _text(listed), "own history stays visible"
    detail = client.get(f"/performance/archive/{env.archives['other']}")
    assert detail.status_code == 403
    before = _archive_count(env)
    assert client.get("/performance/archive/new").status_code == 403
    client.post(
        "/performance/archive/new",
        data={"employee_id": str(env.ids["other"]), "result_year": "2022", "period_label": "CONTRACT-NEW", "score": "91"},
    )
    assert _archive_count(env) == before


@pytest.mark.parametrize("who", ["label_admin", "label_baskan", "label_sysadm", "label_only_admin"])
def test_d3_role_label_never_grants_mobile_scope_or_creation(env, who):
    for path in DIRECTORY_PATHS:
        _assert_self_only(env, who, path)
    for path in ("/api/mobile/personnel/create", "/api/mobile/personnel/add"):
        response, sicil = _create_personnel(env, who, path)
        assert response.status_code == 403, (who, path, response.status_code)
        assert not _user_exists(env, sicil)


def test_d3_role_label_never_grants_ai_decision_or_phase3_global_scope(env):
    """An empty stored role with the display label 'admin' stays at the own scope."""
    from app.extensions import db
    from app.models import User
    from app.services.ai_decision.visibility_scope import build_ai_decision_scope
    from app.services.performance.completion_phase3_visibility_scope import build_visibility_profile

    with env.app.app_context():
        user = db.session.get(User, env.ids["label_only_admin"])
        scope = build_ai_decision_scope(user)
        assert scope.role_group == "own_scope"
        assert scope.can_view_global_summary is False and scope.can_view_person_level_detail is False
        assert build_visibility_profile(user).can_view_global is False


@pytest.mark.parametrize("actor", ["baskan", "grup_baskani", "mali_musavir"])
def test_guard_r02_only_the_admin_role_assigns_the_grant(env, actor):
    before = len(_change_logs(env, "holder"))
    response = _grant_via_settings(env, "holder", actor=actor)
    assert response.status_code == 302
    assert len(_change_logs(env, "holder")) == before + 1, "the save itself must have run"
    assert not _has_active_grant_row(env, "holder")
    _assert_self_only(env, "holder", "/api/mobile/personnel/list")


def test_guard_r02_two_non_admin_admin_family_users_cannot_cross_grant(env):
    _grant_via_settings(env, "mali_musavir", actor="grup_baskani")
    _grant_via_settings(env, "grup_baskani", actor="mali_musavir")
    for who in ("mali_musavir", "grup_baskani"):
        assert not _has_active_grant_row(env, who)
        _assert_self_only(env, who, "/api/mobile/personnel/list")


def test_guard_r02_non_admin_save_keeps_an_existing_grant(env):
    _grant_via_settings(env, "holder")
    assert _has_active_grant_row(env, "holder")
    _save_matrix_without_grant(env, "holder", actor="mali_musavir")
    assert _has_active_grant_row(env, "holder"), "only an admin may revoke"
    _assert_institution_wide(env, "holder", "/api/mobile/personnel/list")


def _add_faz7_archive_columns_and_row(env):
    """migrations/sql/ai_decision_faz7_historical_archive.sql adds these columns in production."""
    from sqlalchemy import text

    from app.extensions import db

    with env.app.app_context():
        for column, column_type in (
            ("user_id", "INTEGER"), ("personnel_id", "INTEGER"), ("registry_no", "VARCHAR(60)"),
            ("personnel_name", "VARCHAR(255)"), ("period_year", "INTEGER"), ("period_title", "VARCHAR(180)"),
            ("score_value", "NUMERIC(10,2)"), ("score_label", "VARCHAR(120)"), ("general_comment", "TEXT"),
            ("visibility_status", "VARCHAR(40) DEFAULT 'active'"),
        ):
            db.session.execute(text(f"ALTER TABLE performance_archived_results ADD COLUMN {column} {column_type}"))
        db.session.execute(
            text(
                "INSERT INTO performance_archived_results (employee_id, result_year, period_label, score, source_type, "
                "created_at, updated_at, user_id, personnel_name, period_year, score_value, general_comment, registry_no) "
                "VALUES (:e, 2024, '2024', 61, 'manual', :n, :n, :e, :name, 2024, 61, 'CONTRACT-FAZ7-COMMENT', :sicil)"
            ),
            {"e": env.ids["other"], "n": datetime.datetime(2025, 1, 1), "name": f"Kisi {SICIL['other']}", "sicil": SICIL["other"]},
        )
        db.session.commit()


@pytest.mark.parametrize("who", ["ik", "pyet", "sysadm"])
def test_r03_ai_decision_archive_gives_no_other_persons_record(env, who):
    _add_faz7_archive_columns_and_row(env)
    client = _web(env, who)
    detail = client.get(f"/ai/decision-support/performance/archive/user/{env.ids['other']}")
    assert detail.status_code == 403
    assert "CONTRACT-FAZ7-COMMENT" not in _text(detail)
    assert _leaked(_text(detail), "other") == []
    summary = client.get("/ai/decision-support/performance/archive/summary")
    assert summary.status_code == 403


def test_positive_admin_keeps_ai_decision_archive_detail(env):
    _add_faz7_archive_columns_and_row(env)
    detail = _web(env, "admin").get(f"/ai/decision-support/performance/archive/user/{env.ids['other']}")
    assert detail.status_code == 200
    assert "CONTRACT-FAZ7-COMMENT" in _text(detail)


def _seed_evaluations(env):
    from app.extensions import db
    from app.models import PerformanceEvaluation, User

    with env.app.app_context():
        for key, category, score in (("other", "Teknik", 55.0), ("evaluatee", "Idari", 95.0), ("personel", "Yonetim", 80.0)):
            db.session.get(User, env.ids[key]).personnel_category = category
            db.session.add(PerformanceEvaluation(period_id=env.period, employee_id=env.ids[key], final_total_100=score))
        db.session.commit()


@pytest.mark.parametrize("who", ["ik", "pyet", "sysadm"])
def test_r04_ai_decision_category_groups_are_not_institution_wide(env, who):
    _seed_evaluations(env)
    response = _web(env, who).get("/ai/decision-support/performance/visible-category-groups")
    groups = ((response.get_json() or {}).get("data") or {}).get("category_groups") or []
    assert response.status_code == 403 or groups == [], (who, response.status_code, groups)


def test_positive_admin_keeps_ai_decision_category_groups(env):
    _seed_evaluations(env)
    response = _web(env, "admin").get("/ai/decision-support/performance/visible-category-groups")
    assert response.status_code == 200
    groups = ((response.get_json() or {}).get("data") or {}).get("category_groups") or []
    assert {group["category"] for group in groups} >= {"Teknik", "Idari", "Yonetim"}


def test_guard_r07_only_the_grant_paths_reference_the_grant_key():
    """Static guard: a new writer of the key must go through the reviewed grant paths."""
    root = Path(__file__).resolve().parents[2] / "app"
    quoted_key = re.compile(r"""["']personnel_read_all["']""")
    literal_files = sorted(
        str(path.relative_to(root.parent)) for path in root.rglob("*.py") if quoted_key.search(path.read_text(encoding="utf-8"))
    )
    assert literal_files == ["app/services/personnel_read_grant.py"], literal_files
    constant_files = sorted(
        str(path.relative_to(root.parent))
        for path in root.rglob("*.py")
        if "PERSONNEL_READ_ALL_KEY" in path.read_text(encoding="utf-8")
    )
    assert constant_files == [
        "app/main_handlers/account_settings_helpers.py",
        "app/main_handlers/account_visibility_helpers.py",
        "app/services/personnel_read_grant.py",
        "app/services/settings_service.py",
    ], constant_files
