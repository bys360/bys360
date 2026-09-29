from __future__ import annotations

import ast
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from openpyxl import Workbook

from app.services import corporate_information_center
from app.services.cic import (
    celebration_service,
    cic_context,
    facade,
    mail_service,
    save_context,
    scheduler_service,
)

ROOT = Path(__file__).resolve().parents[2]
MOVED_CELEBRATION_FUNCTIONS = {
    "_cic_v40_anniversary_users",
    "_cic_v40_birthday_users",
    "_cic_v40_run_weekend_celebrations",
    "_cic_v40_service_year",
    "celebration_context",
    "ensure_celebration_schema",
    "import_celebration_dates_from_excel",
    "save_celebration_settings",
}


def _top_level_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_celebration_functions_have_one_canonical_definition() -> None:
    canonical = ROOT / "app/services/cic/celebration_service.py"
    assert _top_level_definitions(canonical) >= MOVED_CELEBRATION_FUNCTIONS

    for relative in (
        "app/services/cic/cic_context.py",
        "app/services/cic/save_context.py",
        "app/services/corporate_information_center.py",
    ):
        assert not (
            MOVED_CELEBRATION_FUNCTIONS
            & _top_level_definitions(ROOT / relative)
        )

    source = canonical.read_text(encoding="utf-8")
    assert "corporate_information_center as _legacy" not in source
    assert "_legacy." not in source


def test_existing_entry_points_use_canonical_celebration_functions() -> None:
    for name in MOVED_CELEBRATION_FUNCTIONS:
        canonical = getattr(celebration_service, name)
        assert getattr(facade, name) is canonical
        assert not hasattr(corporate_information_center, name)

    assert not (ROOT / "app/services/cic/send_context.py").exists()
    assert not (ROOT / "app/services/cic/run_context.py").exists()
    assert not hasattr(mail_service, "_cic_v40_birthday_users")
    assert not hasattr(mail_service, "_cic_v40_anniversary_users")
    assert not hasattr(mail_service, "_cic_v40_service_year")
    assert not hasattr(cic_context, "_cic_v40_run_weekend_celebrations")
    assert not hasattr(save_context, "ensure_celebration_schema")
    assert not hasattr(save_context, "save_celebration_settings")


def test_birthday_anniversary_and_service_year_contract(monkeypatch) -> None:
    today = date(2026, 7, 20)
    birthday = SimpleNamespace(
        id=1,
        birth_date=date(1990, 7, 20),
        hire_date=date(2020, 7, 20),
    )
    zero_year = SimpleNamespace(
        id=2,
        birth_date=date(1995, 1, 1),
        hire_date=date(2026, 7, 20),
    )

    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_setting_bool",
        lambda _name, _default: True,
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_today",
        lambda _now=None: today,
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_active_staff_candidates",
        lambda: [birthday, zero_year],
    )

    assert celebration_service._cic_v40_birthday_users() == [birthday]
    assert celebration_service._cic_v40_service_year(birthday) == 6
    assert celebration_service._cic_v40_service_year(zero_year) == 0
    assert celebration_service._cic_v40_anniversary_users() == [birthday]


def test_disabled_celebration_switches_return_no_recipients(monkeypatch) -> None:
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_setting_bool",
        lambda _name, _default: False,
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_active_staff_candidates",
        lambda: [SimpleNamespace(id=1)],
    )

    assert celebration_service._cic_v40_birthday_users() == []
    assert celebration_service._cic_v40_anniversary_users() == []


def test_mail_service_resolves_canonical_celebration_recipients(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_birthday_users",
        lambda: ["birthday-user"],
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_anniversary_users",
        lambda: ["anniversary-user"],
    )

    assert mail_service._recipients_for_task("staff_birthday") == [
        "birthday-user"
    ]
    assert mail_service._recipients_for_task("work_anniversary") == [
        "anniversary-user"
    ]


def test_weekend_scheduler_runs_due_enabled_celebration(monkeypatch) -> None:
    calls: list[tuple[str, Any]] = []
    session = SimpleNamespace(
        commit=lambda: calls.append(("commit", None)),
        rollback=lambda: calls.append(("rollback", None)),
    )
    monkeypatch.setattr(
        celebration_service,
        "db",
        SimpleNamespace(session=session),
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_setting_bool",
        lambda name, _default: name == "celebrations_include_weekend",
    )
    monkeypatch.setattr(
        celebration_service,
        "get_config",
        lambda: {
            "tasks": {
                "staff_birthday": {
                    "enabled": True,
                    "hour": 9,
                    "minute": 0,
                }
            }
        },
    )
    monkeypatch.setattr(
        scheduler_service,
        "get_auto_scheduler_config",
        lambda: {"late_window_minutes": 20},
    )
    monkeypatch.setattr(
        celebration_service,
        "get_setting",
        lambda _key, _default="": "",
    )
    monkeypatch.setattr(
        mail_service,
        "send_task",
        lambda task_key, **kwargs: {
            "task_key": task_key,
            "dry_run": kwargs["dry_run"],
        },
    )
    monkeypatch.setattr(
        celebration_service,
        "set_setting",
        lambda key, value, **kwargs: calls.append(
            ("setting", (key, value, kwargs))
        ),
    )

    result = celebration_service._cic_v40_run_weekend_celebrations(
        datetime(2026, 7, 19, 9, 10),
        dry_run=True,
        actor_user_id=7,
    )

    assert [row["task_key"] for row in result] == ["staff_birthday"]
    assert result[0]["result"]["dry_run"] is True
    assert any(kind == "setting" for kind, _payload in calls)
    assert calls[-1] == ("commit", None)


def test_celebration_context_preserves_dashboard_contract(monkeypatch) -> None:
    monkeypatch.setattr(celebration_service, "ensure_defaults", lambda: None)
    monkeypatch.setattr(
        celebration_service,
        "ensure_celebration_schema",
        lambda: {"ok": True, "added": []},
    )
    monkeypatch.setattr(
        celebration_service,
        "context",
        lambda search=None: {"search": search},
    )
    monkeypatch.setattr(
        celebration_service,
        "list_users",
        lambda search=None, limit=0: [f"{search}:{limit}"],
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_birthday_users",
        lambda: ["birthday"],
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_anniversary_users",
        lambda: ["anniversary"],
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_special_days_today",
        lambda: [{"name": "Today"}],
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_special_days",
        lambda: [{"name": "Calendar"}],
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_setting_bool",
        lambda _name, default: default,
    )
    monkeypatch.setattr(
        celebration_service,
        "get_setting",
        lambda _key, default="": default,
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_upcoming_users",
        lambda kind, _days: [kind],
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v40_upcoming_special_days",
        lambda _days: ["special"],
    )

    result = celebration_service.celebration_context("ali")
    payload = result["celebration"]

    assert result["active_tab"] == "celebrations"
    assert result["search"] == "ali"
    assert payload["users"] == ["ali:1000"]
    assert payload["stats"] == {
        "today_total": 3,
        "birthday_count": 1,
        "anniversary_count": 1,
        "special_day_count": 1,
        "upcoming_total": 3,
    }


class _Payload(dict[str, object]):
    def getlist(self, key: str) -> list[object]:
        value = self.get(key, [])
        return list(value) if isinstance(value, list) else []


def test_save_celebration_settings_preserves_settings_and_user_dates(
    monkeypatch,
) -> None:
    saved: list[tuple[str, str, dict[str, object]]] = []
    user = SimpleNamespace(
        birth_date=None,
        hire_date=None,
        celebration_opt_out=False,
    )
    session = SimpleNamespace(
        get=lambda _model, user_id: user if user_id == 7 else None,
        commit=lambda: saved.append(("commit", "", {})),
        rollback=lambda: saved.append(("rollback", "", {})),
    )
    monkeypatch.setattr(
        celebration_service,
        "db",
        SimpleNamespace(session=session),
    )
    monkeypatch.setattr(
        celebration_service,
        "ensure_celebration_schema",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(
        celebration_service,
        "set_setting",
        lambda key, value, **kwargs: saved.append((key, value, kwargs)),
    )

    payload = _Payload(
        celebrations_enabled="1",
        birthday_enabled="1",
        work_anniversary_enabled="1",
        special_day_enabled="1",
        celebration_system_notifications_enabled="1",
        celebrations_include_weekend="0",
        special_day_recipient_mode="manual",
        special_days_json='[{"date": "01-01", "name": "Test"}]',
        user_ids=["7"],
        birth_date_7="20.07.1990",
        hire_date_7="20.07.2020",
        celebration_opt_out_7="1",
    )

    celebration_service.save_celebration_settings(payload, actor_user_id=9)

    assert user.birth_date == date(1990, 7, 20)
    assert user.hire_date == date(2020, 7, 20)
    assert user.celebration_opt_out is True
    assert any(
        key.endswith("special_day_recipient_mode") and value == "manual"
        for key, value, _kwargs in saved
    )
    assert saved[-1][0] == "commit"


def test_ensure_celebration_schema_reports_missing_columns_without_altering(
    monkeypatch,
) -> None:
    from app.services import runtime_schema

    def _no_write_transaction() -> None:
        raise AssertionError("ensure_celebration_schema must not open a write transaction")

    engine = SimpleNamespace(url="sqlite:///consolidation-unit", begin=_no_write_transaction)
    inspector = SimpleNamespace(
        has_table=lambda name: name == "users",
        get_columns=lambda _name: [{"name": "id"}, {"name": "birth_date"}],
    )
    monkeypatch.setattr(runtime_schema, "inspect", lambda _engine: inspector)
    monkeypatch.setattr(runtime_schema, "db", SimpleNamespace(engine=engine))
    monkeypatch.setattr(celebration_service, "db", SimpleNamespace(engine=engine))

    result = celebration_service.ensure_celebration_schema()

    assert result["ok"] is False
    assert result["added"] == []
    warning = result["warnings"][0]
    assert "users.hire_date" in warning
    assert "users.celebration_opt_out" in warning
    assert "users.birth_date" not in warning


def test_excel_import_preview_preserves_match_and_no_write(monkeypatch) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Sicil No", "Doğum Tarihi", "Kutlama Dışı"])
    worksheet.append(["A-7", date(1990, 7, 20), "Evet"])
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    file_storage = SimpleNamespace(filename="celebrations.xlsx", stream=stream)

    monkeypatch.setattr(
        celebration_service,
        "_cic_v45_ensure_schema",
        lambda: None,
    )
    monkeypatch.setattr(
        celebration_service,
        "_cic_v45_existing_user_rows",
        lambda: [
            {
                "id": 7,
                "sicil_no": "A-7",
                "email": "person@example.test",
                "ad": "Test",
                "soyad": "Personel",
            }
        ],
    )

    result = celebration_service.import_celebration_dates_from_excel(
        file_storage,
        apply=False,
        actor_user_id=1,
    )

    assert result["ok"] is True
    assert result["mode"] == "preview"
    assert result["total_rows"] == 1
    assert result["matched"] == 1
    assert result["updated"] == 0
    assert result["unmatched"] == 0
    assert result["preview_rows"][0]["user_id"] == 7
    assert "veritabanına kayıt yazılmadı" in result["warnings"][0]
