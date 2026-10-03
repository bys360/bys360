from __future__ import annotations

from pathlib import Path

import pytest

from scripts.quality import bys360_phase3b_mobile_performance_config_helpers_gate_v1 as gate
from scripts.quality.bys360_phase3b_mobile_performance_config_helpers_gate_v1 import run_checks


def test_phase3b_mobile_performance_config_helpers_gate_v1() -> None:
    root = Path(__file__).resolve().parents[2]
    result = run_checks(root, write_report=False)

    assert result["canonical_item_import_ok"] is True, "Config helpers must import _item from mobile.shared"
    assert result["facade_item_import_absent"] is True, "Config helpers must not import _item from mobile.routes"
    assert result["config_helpers_gate_ok"] is True
    assert result["route_decorator_count"] == 22
    assert result["route_import_ok"] is True
    assert result["service_imports_ok"] is True
    assert result["route_line_reduction_ok"] is True
    assert all(result["helper_presence"].values())
    assert all(result["helper_removed_from_route"].values())


@pytest.mark.parametrize(
    ("import_source", "canonical_ok", "facade_absent", "gate_ok"),
    [
        ("from app.api.mobile.shared import _item", True, True, True),
        ("from app.api.mobile.shared import (\n    _item,\n)", True, True, True),
        ("# from app.api.mobile.shared import _item", False, True, False),
        ('"""from app.api.mobile.shared import _item"""', False, True, False),
        ('"from app.api.mobile.shared import _item"', False, True, False),
        ("from app.api.mobile.routes import _item", False, False, False),
        (
            "from app.api.mobile.shared import _item\nfrom app.api.mobile.routes import _item",
            True, False, False,
        ),
        ("from app.api.mobile.shared import _item\ninvalid syntax !", False, True, False),
    ],
    ids=["canonical", "multiline", "comment", "docstring", "string", "facade", "mixed", "syntax-error"],
)
def test_gate_checks_executable_item_import_ownership(
    monkeypatch: pytest.MonkeyPatch,
    import_source: str,
    canonical_ok: bool,
    facade_absent: bool,
    gate_ok: bool,
) -> None:
    root = Path(__file__).resolve().parents[2]
    original_read = gate._read
    service_path = root / gate.ROOT_REL_SERVICE
    service_text = original_read(service_path)
    for owner in ("routes", "shared"):
        service_text = service_text.replace(f"from app.api.mobile.{owner} import _item", "")
    service_text = service_text.replace(
        "from __future__ import annotations",
        f"from __future__ import annotations\n{import_source}",
        1,
    )

    def read_with_import_case(path: Path) -> str:
        return service_text if path == service_path else original_read(path)

    monkeypatch.setattr(gate, "_read", read_with_import_case)
    result = run_checks(root, write_report=False)

    assert result["canonical_item_import_ok"] is canonical_ok
    assert result["facade_item_import_absent"] is facade_absent
    assert result["config_helpers_gate_ok"] is gate_ok
    assert result["route_exists"] is True
    assert result["service_exists"] is True
    assert result["route_decorator_count"] == 22
    assert result["route_import_ok"] is True
    assert result["service_imports_ok"] is True
    assert result["route_line_reduction_ok"] is True
    assert all(result["helper_presence"].values())
    assert all(result["helper_removed_from_route"].values())
