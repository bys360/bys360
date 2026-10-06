"""performance_development_recommendations has one schema owner and one scorecard contract.

* Schema: Alembic revision 29fee38a97e1 (47 columns). The only other code that may hold DDL for the
  table is the pre-existing runtime-schema provisioner of the same 47-column contract
  (``provision_phase10_recommendation_table``, run only by ``flask runtime-schema provision``).
* The retired legacy P4 contract (source, title, is_required, status, approved_by, approved_at,
  evaluation_id, employee_user_id) must not come back through SQL, DDL or templates.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLE = "performance_development_recommendations"
P4_MODULE = ROOT / "app" / "services" / "performance" / "meeting_p4_development_guidance.py"
P4_ROUTES = ROOT / "app" / "performance" / "meeting_p4_development_guidance_routes.py"
PHASE10_MODULE = ROOT / "app" / "performance" / "phase10_development_guidance_ui.py"
DETAIL_TEMPLATE = ROOT / "app" / "templates" / "performance_scorecard_detail.html"
PDF_TEMPLATE = ROOT / "app" / "templates" / "scorecard_pdf.html"
DDL = re.compile(r"\b(CREATE\s+TABLE|ALTER\s+TABLE|CREATE\s+(UNIQUE\s+)?INDEX|DROP\s+TABLE)\b", re.I)
SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", re.I)
LEGACY_COLUMNS = ("source", "title", "is_required", "status", "approved_by", "approved_at", "evaluation_id", "employee_user_id")


def _string_constants(path: Path) -> list[tuple[str, str]]:
    """(enclosing function name, literal text) for every string literal / f-string part."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found: list[tuple[str, str]] = []

    def visit(node: ast.AST, func: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                found.append((name, child.value))
            visit(child, name)

    visit(tree, "<module>")
    return found


def test_legacy_p4_module_holds_no_ddl_and_no_legacy_table_constants():
    for func, value in _string_constants(P4_MODULE):
        assert not DDL.search(value), f"P4 DDL is retired ({func}): {value[:80]!r}"
    source = P4_MODULE.read_text(encoding="utf-8")
    for retired in ("P4_RECOMMENDATION_COLUMNS", "ensure_recommendation_table", "seed_demo_recommendation", "save_development_recommendation"):
        assert retired not in source, f"{retired} belongs to the retired P4 storage contract"


def test_legacy_p4_module_sql_uses_no_legacy_recommendation_columns():
    for func, value in _string_constants(P4_MODULE):
        if not SQL.search(value):
            continue
        for column in LEGACY_COLUMNS:
            assert not re.search(rf"\b{column}\b", value), f"{func} SQL references legacy column {column!r}"


def test_only_the_approved_mechanisms_define_the_table():
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        for func, value in _string_constants(path):
            if TABLE in value and DDL.search(value):
                offenders.append((path.relative_to(ROOT).as_posix(), func))
    assert offenders == [
        ("app/performance/phase10_development_guidance_ui.py", "provision_phase10_recommendation_table")
    ] * len(offenders)
    assert offenders, "the runtime-schema provisioner of the canonical contract is expected to remain"
    phase10 = PHASE10_MODULE.read_text(encoding="utf-8")
    assert 'provision=provision_phase10_recommendation_table' in phase10
    migrations = [p.name for p in (ROOT / "migrations" / "versions").glob("*.py") if TABLE in p.read_text(encoding="utf-8")]
    assert migrations == ["29fee38a97e1_adopt_performance_development_.py"]


def test_scorecard_templates_consume_only_the_canonical_view_model():
    for template in (DETAIL_TEMPLATE, PDF_TEMPLATE):
        text = template.read_text(encoding="utf-8")
        for legacy in ("item.is_required", "item.title", "item.type_label", "item.created_display", "can_add_note", "performance_scorecard_development_note_save"):
            assert legacy not in text, f"{template.name} still uses legacy P4 field {legacy}"
        assert "render_scorecard_guidance_items" in text


def test_pdf_template_is_one_html_document():
    text = PDF_TEMPLATE.read_text(encoding="utf-8")
    assert text.count("</html>") == 1
    tail = text.split("</html>", 1)[1]
    assert re.sub(r"\{#.*?#\}", "", tail, flags=re.S).strip() == "", "nothing may render after </html>"


def test_legacy_writer_routes_no_longer_persist_recommendations():
    routes = P4_ROUTES.read_text(encoding="utf-8")
    assert "save_development_recommendation" not in routes
    assert "build_p4_development_guidance_context" not in routes
