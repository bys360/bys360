"""Personnel list bulk delete / bulk archive: selection contract and F3 protection.

Defect (2026-10-16)
-------------------
``/personnel`` renders ``personnel_list.html``. Its "Toplu Sil" / "Toplu Arşivle" forms (posting to
``/admin/users/bulk-delete`` / ``bulk-archive``) put
the ticked ids into ONE hidden field ``selected_ids`` as a comma-joined string (``"12,15,18"``),
while ``admin_users_bulk_delete_impl`` / ``admin_users_bulk_archive_impl`` read only
``request.form.getlist("user_ids")``. The selection therefore always arrived empty and both
buttons ended with "Lütfen en az bir personel seçin." without touching any record.

Security review of the same path
--------------------------------
F3 (R05c, ``split_bulk_targets``): a bulk change never touches a protected account (own
account, any role other than ``personel``, a visible ``personnel_read_all`` / ``support_all``
holder), whoever runs it. Bulk delete and bulk archive only applied the non-admin R05 check,
so a real admin's bulk run deleted or archived protected accounts.

Contract
--------
- the page posts ``user_ids``; the endpoints accept repeated ``user_ids`` fields (the existing
  format), a comma-joined value, and the previous field name ``selected_ids`` (an open tab);
- only positive ids count: blanks, non-numbers, signs and repeats are dropped; unknown ids are
  reported, never counted; more than ``MAX_BULK_SELECTION`` ids change nothing;
- the personnel list sends ``return_to=personnel_list`` and comes back to ``/personnel``; every
  other caller still lands on ``/admin/users`` (allowlist, no open redirect);
- protected accounts are skipped for every actor, audited (``account.change_refused``) and
  reported; nothing outside the selection changes;
- protection is checked again right before each deletion;
- a failed deletion rolls back that account only (no orphan ``account.delete`` row).

Tests named ``test_guard_*`` also pass on the pre-fix code (77b2f6d9); every other test fails
there and passes with the fix.
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.security import test_r05_account_change_authority_contract as r05

env = r05.env

SUMMARY_WARNING_TAIL = "Silinemeyen kayıtlar ilişkili veri içeriyor olabilir."


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _post(client: Any, path: str, data: dict[str, Any]) -> tuple[Any, list[tuple[str, str]]]:
    response = client.post(path, data=data, follow_redirects=False)
    with client.session_transaction() as sess:
        flashes = [(str(category), str(message)) for category, message in sess.get("_flashes", [])]
    return response, flashes


def _csv(env: Any, *keys: str) -> str:
    return ",".join(str(env.ids[key]) for key in keys)


def _snapshot(env: Any) -> dict[str, Any]:
    return {key: r05._state(env, key) for key in r05._USERS}


def _unchanged_except(env: Any, before: dict[str, Any], changed: set[str]) -> None:
    after = _snapshot(env)
    for key in r05._USERS:
        if key in changed:
            continue
        assert after[key] == before[key], key


def _refusal_rows(env: Any, reason: str) -> list[Any]:
    return [row for row in r05._audit_rows(env, "account.change_refused") if reason in row.raw]


def _messages(flashes: list[tuple[str, str]]) -> str:
    return " | ".join(message for _category, message in flashes)


# --------------------------------------------------------------------------------------
# The page itself
# --------------------------------------------------------------------------------------


def test_personnel_list_bulk_forms_post_user_ids(env):
    client = r05._web(env, "admin")
    response = client.get("/personnel")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="user_ids" id="bulkArchiveIds"' in html
    assert 'name="user_ids" id="bulkDeleteIds"' in html
    assert 'name="selected_ids"' not in html
    assert html.count('name="return_to" value="personnel_list"') == 2
    # the forms keep their CSRF field and the selection script
    assert html.count('name="csrf_token"') >= 2
    assert "function fillBulkIds(targetId, confirmText)" in html


# --------------------------------------------------------------------------------------
# Bulk delete: selection formats
# --------------------------------------------------------------------------------------


def test_bulk_delete_comma_joined_selection_deletes_exactly_the_selection(env):
    before = _snapshot(env)
    response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-delete", {"user_ids": _csv(env, "plain", "plain2")})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/users")
    assert flashes[-1] == ("success", "Toplu silme tamamlandı. Silinen kayıt: 2")
    assert r05._state(env, "plain") is None
    assert r05._state(env, "plain2") is None
    _unchanged_except(env, before, {"plain", "plain2"})
    deleted = {row.entity_id for row in r05._audit_rows(env, "account.delete")}
    assert deleted == {env.ids["plain"], env.ids["plain2"]}


def test_bulk_delete_accepts_the_previous_selected_ids_field(env):
    """An admin tab opened before the deploy still posts ``selected_ids``."""
    _response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-delete", {"selected_ids": _csv(env, "plain", "plain2")})
    assert flashes[-1] == ("success", "Toplu silme tamamlandı. Silinen kayıt: 2")
    assert r05._state(env, "plain") is None
    assert r05._state(env, "plain2") is None


def test_guard_bulk_delete_keeps_the_repeated_user_ids_format(env):
    before = _snapshot(env)
    _response, flashes = _post(
        r05._web(env, "admin"),
        "/admin/users/bulk-delete",
        {"user_ids": [str(env.ids["plain"]), str(env.ids["plain2"])]},
    )
    assert flashes[-1] == ("success", "Toplu silme tamamlandı. Silinen kayıt: 2")
    _unchanged_except(env, before, {"plain", "plain2"})


def test_guard_bulk_delete_single_selection(env):
    before = _snapshot(env)
    _response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-delete", {"user_ids": str(env.ids["plain"])})
    assert flashes[-1] == ("success", "Toplu silme tamamlandı. Silinen kayıt: 1")
    _unchanged_except(env, before, {"plain"})


@pytest.mark.parametrize(
    "data",
    [{}, {"user_ids": ""}, {"selected_ids": ""}, {"user_ids": " , ,"}, {"user_ids": "abc"}],
    ids=["missing", "empty", "empty-legacy", "only-separators", "not-a-number"],
)
def test_guard_bulk_delete_without_a_valid_selection_changes_nothing(env, data):
    before = _snapshot(env)
    response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-delete", data)
    assert response.status_code == 302
    assert flashes[-1] == ("warning", "Lütfen en az bir personel seçin.")
    _unchanged_except(env, before, set())
    assert not r05._audit_rows(env, "account.delete")


def test_bulk_delete_drops_invalid_and_repeated_ids_and_reports_unknown_ones(env):
    before = _snapshot(env)
    plain = str(env.ids["plain"])
    _response, flashes = _post(
        r05._web(env, "admin"),
        "/admin/users/bulk-delete",
        {"user_ids": f"{plain}, abc,{plain},,999999,-3,+{plain},0", "selected_ids": plain},
    )
    assert flashes[-1] == ("success", "Toplu silme tamamlandı. Silinen kayıt: 1")
    assert "1 seçili kayıt bulunamadı" in _messages(flashes)
    _unchanged_except(env, before, {"plain"})
    assert [row.entity_id for row in r05._audit_rows(env, "account.delete")] == [env.ids["plain"]]


# --------------------------------------------------------------------------------------
# Bulk delete: R05 / F3 protection
# --------------------------------------------------------------------------------------


def test_f3_real_admin_bulk_delete_skips_every_protected_account(env):
    before = _snapshot(env)
    selection = _csv(env, "admin2", "koordinator", "sysadm", "pra_holder", "sup_holder", "baskan", "plain")
    _response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-delete", {"user_ids": selection})
    assert flashes[-1] == ("warning", f"Toplu silme tamamlandı. Silinen: 1, silinemeyen: 6. {SUMMARY_WARNING_TAIL}")
    assert "6 korumalı hesap toplu işlemden çıkarıldı" in _messages(flashes)
    assert r05._state(env, "plain") is None
    _unchanged_except(env, before, {"plain"})
    refused = {row.entity_id for row in _refusal_rows(env, "bulk_delete")}
    assert refused == {env.ids[key] for key in ("admin2", "koordinator", "sysadm", "pra_holder", "sup_holder", "baskan")}
    assert [row.entity_id for row in r05._audit_rows(env, "account.delete")] == [env.ids["plain"]]


def test_bulk_delete_never_deletes_the_actor_and_audits_the_refusal(env):
    before = _snapshot(env)
    _response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-delete", {"user_ids": _csv(env, "admin", "plain")})
    assert flashes[-1] == ("warning", f"Toplu silme tamamlandı. Silinen: 1, silinemeyen: 1. {SUMMARY_WARNING_TAIL}")
    assert r05._state(env, "admin") is not None
    _unchanged_except(env, before, {"plain"})
    assert {row.entity_id for row in _refusal_rows(env, "bulk_delete")} == {env.ids["admin"]}


def test_non_admin_editor_bulk_delete_with_comma_joined_selection_skips_protected_accounts(env):
    before = _snapshot(env)
    _response, flashes = _post(
        r05._web(env, "baskan"), "/admin/users/bulk-delete", {"user_ids": _csv(env, "admin2", "pra_holder", "plain")}
    )
    assert flashes[-1] == ("warning", f"Toplu silme tamamlandı. Silinen: 1, silinemeyen: 2. {SUMMARY_WARNING_TAIL}")
    _unchanged_except(env, before, {"plain"})
    assert r05._state(env, "plain") is None


@pytest.mark.parametrize("path", ["/admin/users/bulk-delete", "/admin/users/bulk-archive"])
def test_guard_bulk_endpoints_reject_a_non_admin_family_user(env, path):
    before = _snapshot(env)
    client = r05._web(env, "plain")
    response = client.post(path, data={"user_ids": _csv(env, "plain2", "koordinator")}, follow_redirects=False)
    assert response.status_code == 403
    _unchanged_except(env, before, set())


def test_guard_bulk_delete_failure_rolls_back_only_that_account(env, monkeypatch):
    from app.admin import ops_user_action_services as services

    real_delete = services.safe_delete_user_by_id
    failing_id = env.ids["plain2"]

    def _failing_delete(user_id: int, **kwargs: Any) -> Any:
        if int(user_id) == failing_id:
            real_delete(user_id, **kwargs)  # the rows really are touched before the failure
            raise RuntimeError("simulated failure after the delete statements")
        return real_delete(user_id, **kwargs)

    monkeypatch.setattr(services, "safe_delete_user_by_id", _failing_delete)
    before = _snapshot(env)
    _response, flashes = _post(
        r05._web(env, "admin"), "/admin/users/bulk-delete", {"user_ids": [str(env.ids["plain"]), str(failing_id)]}
    )
    assert flashes[-1] == ("warning", f"Toplu silme tamamlandı. Silinen: 1, silinemeyen: 1. {SUMMARY_WARNING_TAIL}")
    assert r05._state(env, "plain") is None
    assert r05._state(env, "plain2") == before["plain2"]
    _unchanged_except(env, before, {"plain"})
    assert [row.entity_id for row in r05._audit_rows(env, "account.delete")] == [env.ids["plain"]]


# --------------------------------------------------------------------------------------
# Bulk archive
# --------------------------------------------------------------------------------------


def test_bulk_archive_comma_joined_selection_archives_exactly_the_selection(env):
    before = _snapshot(env)
    response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-archive", {"user_ids": _csv(env, "plain", "plain2")})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/users")
    assert flashes[-1] == ("success", "Toplu arşivleme tamamlandı. Güncellenen kayıt: 2")
    assert r05._state(env, "plain").is_active is False
    assert r05._state(env, "plain2").is_active is False
    _unchanged_except(env, before, {"plain", "plain2"})
    changed = {row.entity_id for row in r05._audit_rows(env, "account.activation_change")}
    assert changed == {env.ids["plain"], env.ids["plain2"]}


def test_bulk_archive_accepts_the_previous_selected_ids_field(env):
    _response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-archive", {"selected_ids": _csv(env, "plain")})
    assert flashes[-1] == ("success", "Toplu arşivleme tamamlandı. Güncellenen kayıt: 1")
    assert r05._state(env, "plain").is_active is False


def test_guard_bulk_archive_keeps_the_repeated_user_ids_format(env):
    _response, flashes = _post(
        r05._web(env, "admin"), "/admin/users/bulk-archive", {"user_ids": [str(env.ids["plain"]), str(env.ids["plain2"])]}
    )
    assert flashes[-1] == ("success", "Toplu arşivleme tamamlandı. Güncellenen kayıt: 2")


def test_bulk_archive_drops_invalid_and_repeated_ids(env):
    before = _snapshot(env)
    plain = str(env.ids["plain"])
    _response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-archive", {"user_ids": f"{plain},x,{plain},999999"})
    assert flashes[-1] == ("success", "Toplu arşivleme tamamlandı. Güncellenen kayıt: 1")
    assert "1 seçili kayıt bulunamadı" in _messages(flashes)
    _unchanged_except(env, before, {"plain"})


def test_f3_real_admin_bulk_archive_skips_every_protected_account(env):
    before = _snapshot(env)
    selection = _csv(env, "admin", "admin2", "koordinator", "sysadm", "pra_holder", "sup_holder", "plain")
    _response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-archive", {"user_ids": selection})
    assert flashes[-1] == ("success", "Toplu arşivleme tamamlandı. Güncellenen kayıt: 1")
    assert "6 korumalı hesap toplu işlemden çıkarıldı" in _messages(flashes)
    assert r05._state(env, "plain").is_active is False
    _unchanged_except(env, before, {"plain"})
    rows = _refusal_rows(env, "bulk_archive")
    assert rows, "the skipped accounts are audited"
    audited: set[int] = set()
    for row in rows:
        reason = str((row.new or {}).get("reason", ""))
        audited.update(int(part) for part in reason.rsplit(":", 1)[-1].split(",") if part.strip().isdigit())
    assert audited == {env.ids[key] for key in ("admin", "admin2", "koordinator", "sysadm", "pra_holder", "sup_holder")}


# --------------------------------------------------------------------------------------
# F3 in the existing repeated ``user_ids`` format (fails on the base for the F3 reason)
# --------------------------------------------------------------------------------------

_PROTECTED_FOR_ADMIN = ("admin2", "koordinator", "sysadm", "pra_holder", "sup_holder")


def test_f3_real_admin_bulk_delete_repeated_user_ids_keeps_protected_accounts(env):
    before = _snapshot(env)
    data = {"user_ids": [str(env.ids[key]) for key in (*_PROTECTED_FOR_ADMIN, "plain")]}
    _response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-delete", data)
    assert flashes[-1] == ("warning", f"Toplu silme tamamlandı. Silinen: 1, silinemeyen: 5. {SUMMARY_WARNING_TAIL}")
    _unchanged_except(env, before, {"plain"})
    assert {row.entity_id for row in _refusal_rows(env, "bulk_delete")} == {env.ids[key] for key in _PROTECTED_FOR_ADMIN}


def test_f3_real_admin_bulk_archive_repeated_user_ids_keeps_protected_accounts(env):
    before = _snapshot(env)
    data = {"user_ids": [str(env.ids[key]) for key in (*_PROTECTED_FOR_ADMIN, "plain")]}
    _response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-archive", data)
    assert flashes[-1] == ("success", "Toplu arşivleme tamamlandı. Güncellenen kayıt: 1")
    _unchanged_except(env, before, {"plain"})
    assert r05._state(env, "plain").is_active is False


def test_bulk_delete_rechecks_protection_right_before_deleting(env, monkeypatch):
    """A grant given to a selected account after the split (here: while the first refusal is
    being audited) still protects it."""
    from app.admin import ops_user_action_services as services
    from app.extensions import db
    from app.models import UserMenuPermission

    real_audit = services.audit_refusal
    target_id = env.ids["plain2"]

    def _audit_then_grant(target: Any, reason: str, **kwargs: Any) -> None:
        real_audit(target, reason, **kwargs)
        if not UserMenuPermission.query.filter_by(user_id=target_id, menu_key="personnel_read_all").first():
            db.session.add(
                UserMenuPermission(user_id=target_id, menu_key="personnel_read_all", is_visible=True, source_type="user_override")
            )
            db.session.commit()

    monkeypatch.setattr(services, "audit_refusal", _audit_then_grant)
    data = {"user_ids": [str(env.ids["koordinator"]), str(target_id), str(env.ids["plain"])]}
    _response, flashes = _post(r05._web(env, "admin"), "/admin/users/bulk-delete", data)
    assert flashes[-1] == ("warning", f"Toplu silme tamamlandı. Silinen: 1, silinemeyen: 2. {SUMMARY_WARNING_TAIL}")
    assert r05._state(env, "plain2") is not None
    assert r05._state(env, "koordinator") is not None
    assert r05._state(env, "plain") is None


@pytest.mark.parametrize("path", ["/admin/users/bulk-delete", "/admin/users/bulk-archive"])
def test_bulk_selection_above_the_limit_changes_nothing(env, path):
    from app.admin.ops_user_action_services import MAX_BULK_SELECTION

    before = _snapshot(env)
    ids = [str(env.ids["plain"])] + [str(10_000_000 + n) for n in range(MAX_BULK_SELECTION)]
    _response, flashes = _post(r05._web(env, "admin"), path, {"user_ids": ",".join(ids)})
    assert flashes[-1] == ("warning", f"Tek seferde en fazla {MAX_BULK_SELECTION} personel seçilebilir; işlem yapılmadı.")
    _unchanged_except(env, before, set())


@pytest.mark.parametrize("path", ["/admin/users/bulk-delete", "/admin/users/bulk-archive"])
def test_personnel_list_bulk_forms_return_to_the_personnel_list(env, path):
    response, _flashes = _post(
        r05._web(env, "admin"), path, {"user_ids": str(env.ids["plain"]), "return_to": "personnel_list"}
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/personnel")


@pytest.mark.parametrize("return_to", ["", "https://example.com/", "//evil.example/", "admin_users"])
def test_guard_bulk_redirect_ignores_any_other_return_to(env, return_to):
    response, _flashes = _post(
        r05._web(env, "admin"), "/admin/users/bulk-archive", {"user_ids": [str(env.ids["plain"])], "return_to": return_to}
    )
    assert response.headers["Location"].endswith("/admin/users")
