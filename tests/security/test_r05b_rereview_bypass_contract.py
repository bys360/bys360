"""R05 independent re-review (PR #70 at e2832218): the bypasses it confirmed stay closed.

The re-review ran 13 probes that each asserted an INSECURE outcome and passed. These tests assert
the safe outcome of the same steps (approved policy: role_label, title or free text never create
authority; only the admin role assigns broad rights; unknown scope is denied):

- P1/P1c: a non-admin cannot change the per-user matrix of a protected account (support_all
  holder, the real admin) through /settings, so it cannot strip protection or menus.
- P2*: a job title (unvan) does not open the performance period center, its operator POST, live
  tracking or the evaluator reminder center.
- P3*: a blank role is stored as the baseline role, never as an empty role that a later title
  inference promotes.
- P4: a routine admin import never rewrites a stored role from a title.
- P5: a non-admin cannot add itself to a manager chain or change a protected account's chain.

Not closed here:
- P1b (a non-admin granting support_all) belongs to PR #65 (K5-Q2).
- P2c (the personnel-support publish approval recognises its group chair by title) is OPEN:
  the approved approval-workflow contracts identify the chair by title on a 'personel' account,
  so changing it needs a human decision on how the chair is stored.
"""
from __future__ import annotations

from tests.security import test_r05_account_change_authority_contract as _r05
from tests.security.test_r05_account_change_authority_contract import (
    NEW_PASSWORD,
    SICIL,
    _admin_edit_form,
    _login_succeeds,
    _personnel_edit_form,
    _state,
    _upload,
    _user_by_sicil,
    _web,
    _xlsx_row,
)

env = _r05.env  # the R05 fixture: seeded accounts, explicit grants, temp SQLite

PERIOD_CENTER = "/performance/v2-1-7-period-management-center"
TRACKING_PATHS = (
    "/performance/v2-1-10-evaluation-live-tracking",
    "/performance/v2-1-11-evaluator-reminder-center",
    "/performance/v2-1-11-evaluator-reminder-center/export.csv",
)


def _reload(env, key_or_id):
    from app.extensions import db
    from app.models import User

    user_id = env.ids[key_or_id] if isinstance(key_or_id, str) else key_or_id
    with env.app.app_context():
        user = db.session.get(User, user_id)
        db.session.expunge(user)
        return user


def _visible_rows(env, key, menu_key):
    from app.models import UserMenuPermission

    with env.app.app_context():
        return [
            (row.is_visible, row.source_type)
            for row in UserMenuPermission.query.filter_by(user_id=env.ids[key], menu_key=menu_key).all()
        ]


def _ok(response) -> bool:
    return response.status_code == 200 and "/login" not in response.headers.get("Location", "")


def _refusals(env, reason):
    from app.models import AuditLog

    with env.app.app_context():
        return [
            row
            for row in AuditLog.query.filter_by(action="account.change_refused").all()
            if reason in (row.summary or "")
        ]


# P1 / P1c: /settings per-user matrix of protected accounts --------------------------------


def test_p1_non_admin_cannot_reset_support_all_holder_matrix_nor_take_it_over(env):
    before = _state(env, "sup_holder")
    rows_before = _visible_rows(env, "sup_holder", "support_all")
    assert rows_before, "seeded support_all row"
    client = _web(env, "baskan")
    client.post("/settings", data={"form_action": "reset_user_overrides", "user_id": env.ids["sup_holder"]})
    assert _visible_rows(env, "sup_holder", "support_all") == rows_before
    assert _refusals(env, "settings_user_matrix")
    client.post(
        f"/personnel/{env.ids['sup_holder']}/edit",
        data=_personnel_edit_form(env, "sup_holder", new_password=NEW_PASSWORD, new_password_repeat=NEW_PASSWORD),
    )
    assert _state(env, "sup_holder").password_hash == before.password_hash
    assert not _login_succeeds(env, "sup_holder", NEW_PASSWORD)


def test_p1c_non_admin_cannot_strip_the_real_admin_menus(env):
    assert _web(env, "admin").get("/personnel").status_code == 200
    _web(env, "baskan").post("/settings", data={"form_action": "save_user_visibility", "user_id": env.ids["admin"]})
    assert _web(env, "admin").get("/personnel").status_code == 200


def test_p1c_non_admin_cannot_change_the_admin_role_profile(env):
    from app.models import RoleMenuDefault

    def admin_profile():
        with env.app.app_context():
            return sorted(
                (row.menu_key, bool(row.is_visible)) for row in RoleMenuDefault.query.filter_by(role_name="admin").all()
            )

    client = _web(env, "baskan")
    client.get("/settings")
    before = admin_profile()  # role defaults are seeded on the first request
    assert any(visible for _key, visible in before)
    client.post(
        "/settings",
        data={"form_action": "save_role_profile", "user_id": env.ids["plain"], "profile_role_target": "admin"},
    )
    assert admin_profile() == before
    assert _refusals(env, "settings_admin_role_profile")


def test_p1_non_admin_cannot_change_another_leadership_or_technical_matrix(env):
    for target in ("baskan_yardimcisi", "sysadm", "admin2"):
        before = _visible_rows(env, target, "personnel")
        _web(env, "baskan").post("/settings", data={"form_action": "reset_user_overrides", "user_id": env.ids[target]})
        assert _visible_rows(env, target, "personnel") == before, target
    assert len(_refusals(env, "settings_user_matrix")) == 3


def test_p1_real_admin_still_manages_the_protected_matrix(env):
    client = _web(env, "admin")
    client.post("/settings", data={"form_action": "reset_user_overrides", "user_id": env.ids["sup_holder"]})
    assert _visible_rows(env, "sup_holder", "support_all") == []


# P2: the job title never creates performance-administration authority ----------------------


def test_p2_self_title_admin_does_not_open_period_center_nor_its_operator_post(env):
    client = _web(env, "baskan_yardimcisi")
    assert not _ok(client.get(PERIOD_CENTER))
    client.post(
        f"/personnel/{env.ids['baskan_yardimcisi']}/edit",
        data=_personnel_edit_form(env, "baskan_yardimcisi", unvan="Admin"),
    )
    assert _reload(env, "baskan_yardimcisi").unvan == "Admin"
    client = _web(env, "baskan_yardimcisi")
    assert not _ok(client.get(PERIOD_CENTER))
    response = client.post(
        PERIOD_CENTER,
        data={"action": "prepare_plan", "category_key": "diger", "plan_name": "R5 probe plan", "period_type": "special"},
        follow_redirects=True,
    )
    assert "Dönem hazırlık planı oluşturuldu" not in response.get_data(as_text=True)


def test_p2_title_on_ordinary_account_grants_no_period_center_authority(env):
    from app.performance.v2_1_7_period_management_center_routes import (
        _is_period_center_operator_user,
        _period_center_is_admin_user_v222a,
    )

    editor = _web(env, "mali_musavir")
    for title in ("Yönetici", "Admin", "Sistem Yöneticisi"):
        editor.post(f"/personnel/{env.ids['plain']}/edit", data=_personnel_edit_form(env, "plain", unvan=title))
        user = _reload(env, "plain")
        assert user.unvan == title and user.role == "personel"
        assert not _period_center_is_admin_user_v222a(user), title
        assert not _is_period_center_operator_user(user), title
    assert not _ok(_web(env, "plain").get(PERIOD_CENTER))


def test_p2_title_does_not_open_live_tracking_or_reminder_center(env):
    plain = _web(env, "plain")
    before = {path: plain.get(path).status_code for path in TRACKING_PATHS}
    assert all(code != 200 for code in before.values()), before
    _web(env, "grup_baskani").post(
        f"/personnel/{env.ids['plain']}/edit", data=_personnel_edit_form(env, "plain", unvan="Yönetici")
    )
    plain = _web(env, "plain")
    after = {path: plain.get(path).status_code for path in TRACKING_PATHS}
    assert all(code != 200 for code in after.values()), after


# P3 / P4: no blank role, no title-to-role rewrite --------------------------------------------


def _create_form(sicil, role, unvan):
    return {
        "ad": "Yeni",
        "soyad": sicil,
        "sicil_no": sicil,
        "email": f"{sicil.lower()}@example.gov.tr",
        "unvan": unvan,
        "role": role,
        "birim": "R05 Birim",
        "ust_birim": "R05 Ust Birim",
        "personnel_category": "Diğer",
        "is_active": "on",
    }


def test_p3_blank_role_is_stored_as_baseline_and_not_promoted_by_admin_import(env):
    _web(env, "mali_musavir").post("/admin/users/create", data=_create_form("R5BLANK1", "   ", "Başkan"))
    created = _user_by_sicil(env, "R5BLANK1")
    assert created is not None and created.role == "personel"
    _upload(_web(env, "admin"), "/personnel/excel-upload", [_xlsx_row("R5UNREL1", "personel")], activate_new_users="on")
    assert _user_by_sicil(env, "R5BLANK1").role == "personel"
    assert _web(env, "plain").get("/performance/president-approvals").status_code != 200


def test_p3_admin_blank_role_is_stored_as_baseline(env):
    _web(env, "admin").post("/admin/users/create", data=_create_form("R5BLANK2", "   ", "Koordinatör"))
    assert _user_by_sicil(env, "R5BLANK2").role == "personel"


def test_p4_admin_import_never_rewrites_a_stored_role_from_a_title(env):
    editor = _web(env, "baskan")
    editor.post(f"/admin/users/{env.ids['sysadm']}/edit", data=_admin_edit_form(env, "sysadm", unvan="Başkan Yardımcısı"))
    editor.post(f"/personnel/{env.ids['plain']}/edit", data=_personnel_edit_form(env, "plain", unvan="Başkan"))
    _upload(_web(env, "admin"), "/personnel/excel-upload", [_xlsx_row("R5UNREL2", "personel")], activate_new_users="on")
    assert _state(env, "sysadm").role == "sistem_yoneticisi"
    assert _state(env, "plain").role == "personel"


def test_p4_hierarchy_auto_build_by_admin_never_rewrites_roles_from_titles(env):
    from app.extensions import db
    from app.models import User
    from app.services.auto_hierarchy_service import auto_apply_manager_chains

    with env.app.app_context():
        plain = db.session.get(User, env.ids["plain"])
        plain.unvan = "Başkan"
        db.session.commit()
    with env.app.test_request_context():
        users = User.query.all()
        auto_apply_manager_chains(users, persist_inferred_roles=True)
        db.session.commit()
    assert _state(env, "plain").role == "personel"
    assert _state(env, "sysadm").role == "sistem_yoneticisi"


# P5: manager chains ---------------------------------------------------------------------------


def test_p5_non_admin_cannot_bulk_assign_itself_as_manager(env):
    editor = _web(env, "mali_musavir")
    editor.post(
        "/performance/hierarchy-settings/bulk-assign",
        data={"role": "baskan", "bulk_yonetici_sicil": SICIL["mali_musavir"]},
    )
    assert (_reload(env, "baskan").yonetici_sicil or "") != SICIL["mali_musavir"]
    editor.post(
        "/performance/hierarchy-settings/bulk-assign",
        data={"role": "personel", "bulk_yonetici_sicil": SICIL["mali_musavir"]},
    )
    assert (_reload(env, "plain").yonetici_sicil or "") != SICIL["mali_musavir"]
    assert _refusals(env, "bulk_manager_chain_change")


def test_p5_non_admin_cannot_change_protected_chain_nor_add_itself(env):
    editor = _web(env, "mali_musavir")
    editor.post(
        f"/admin/users/{env.ids['sup_holder']}/edit",
        data=_admin_edit_form(env, "sup_holder", yonetici_sicil=SICIL["mali_musavir"]),
    )
    assert (_reload(env, "sup_holder").yonetici_sicil or "") != SICIL["mali_musavir"]
    editor.post(
        f"/admin/users/{env.ids['plain']}/edit",
        data=_admin_edit_form(env, "plain", yonetici_sicil=SICIL["mali_musavir"]),
    )
    assert (_reload(env, "plain").yonetici_sicil or "") != SICIL["mali_musavir"]
    # Another evaluator for an ordinary account stays allowed.
    editor.post(
        f"/admin/users/{env.ids['plain']}/edit",
        data=_admin_edit_form(env, "plain", yonetici_sicil=SICIL["koordinator"]),
    )
    assert _reload(env, "plain").yonetici_sicil == SICIL["koordinator"]


def test_p5_real_admin_still_assigns_manager_chains(env):
    _web(env, "admin").post(
        f"/admin/users/{env.ids['baskan_yardimcisi']}/edit",
        data=_admin_edit_form(env, "baskan_yardimcisi", yonetici_sicil=SICIL["baskan"]),
    )
    assert _reload(env, "baskan_yardimcisi").yonetici_sicil == SICIL["baskan"]
