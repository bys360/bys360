"""G3-B architecture guards: readiness/read helpers never own the caller's transaction.

Guards the boundary approved in HD-10 Option A, not every commit in the subsystem:

1. ``ensure_interim_notes_table`` (both modules) inspects only: no commit, rollback, flush,
   savepoint or DDL.
2. Request read/readiness helpers (notes reader, workspace/scorecard note builders, mobile
   readiness wrapper) do not call commit or rollback.
3. The assignment GET path cannot reach write-intent evaluation creation; the workspace read
   model never adds, flushes or commits.
4. No request-time DDL for ``performance_interim_notes`` anywhere under ``app/``.
5. No replacement "temporary commit" readiness helper appears in the interim-notes/workspace
   modules.
6. The explicit business operations own persistence through one write-side creator, and the
   route owns the commit.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
RUNTIME = APP / "services" / "performance" / "interim_notes_runtime.py"
P2 = APP / "services" / "performance" / "meeting_p2_archive_notes.py"
WORKSPACE = APP / "services" / "performance_v2" / "evaluation_workspace.py"
ROUTES = APP / "performance" / "v2_routes.py"
MOBILE_ROUTES = APP / "api" / "mobile" / "performance_routes.py"
TRANSACTION_CONTROL = {"commit", "rollback", "flush", "begin_nested", "begin"}
WRITE_SIDE_CREATOR = "get_or_create_evaluation_for_write"
WRITE_SIDE_INTERNALS = {"_create_evaluation_for_write", "_align_evaluator_for_write", WRITE_SIDE_CREATOR}
INTERIM_NOTES_DDL = re.compile(
    r"\b(CREATE\s+(UNIQUE\s+)?(TABLE|INDEX)|ALTER\s+TABLE|DROP\s+TABLE)\b[^;]*\bperformance_interim_notes\b(?!_live)",
    re.I | re.S,
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _functions(path: Path) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in ast.walk(_tree(path)) if isinstance(node, ast.FunctionDef)}


def _attribute_calls(node: ast.AST) -> set[str]:
    return {
        call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    }


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            if isinstance(call.func, ast.Name):
                names.add(call.func.id)
            elif isinstance(call.func, ast.Attribute):
                names.add(call.func.attr)
    return names


def _strings(node: ast.AST) -> list[str]:
    return [item.value for item in ast.walk(node) if isinstance(item, ast.Constant) and isinstance(item.value, str)]


def _reachable(functions: dict[str, ast.FunctionDef], start: str) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        name = stack.pop()
        if name in seen or name not in functions:
            continue
        seen.add(name)
        stack.extend(_called_names(functions[name]) & set(functions))
    return seen


def test_readiness_helpers_only_inspect_the_schema():
    for path in (RUNTIME, P2):
        helper = _functions(path)["ensure_interim_notes_table"]
        assert not (_attribute_calls(helper) & TRANSACTION_CONTROL), path
        assert not any(re.search(r"\b(CREATE|ALTER|DROP)\b", value, re.I) for value in _strings(helper)), path
        assert "execute" not in _attribute_calls(helper), path


def test_request_read_helpers_do_not_own_the_callers_transaction():
    runtime = _functions(RUNTIME)
    for name in ("_schema_ready", "_fetch_notes_from_manager_page", "build_interim_notes_context", "build_scorecard_interim_notes"):
        assert not (_attribute_calls(runtime[name]) & TRANSACTION_CONTROL), name
    mobile = _functions(MOBILE_ROUTES)["_v2853_ensure_interim_notes_table"]
    assert not (_attribute_calls(mobile) & TRANSACTION_CONTROL)


def test_interim_notes_runtime_has_no_transaction_control_at_all():
    assert not (_attribute_calls(_tree(RUNTIME)) & TRANSACTION_CONTROL)


def test_workspace_read_model_cannot_reach_write_intent_or_persistence():
    functions = _functions(WORKSPACE)
    reachable = _reachable(functions, "build_workspace_context")
    assert not (reachable & WRITE_SIDE_INTERNALS)
    assert "_ensure_evaluation" not in functions
    for name in reachable:
        calls = _attribute_calls(functions[name])
        assert not (calls & (TRANSACTION_CONTROL | {"add", "add_all", "delete", "merge"})), name


def test_assignment_get_branch_is_the_only_workspace_builder_and_post_returns_first():
    view = _functions(ROUTES)["performance_v2_phase3_assignment"]
    statements = view.body
    post_index = next(
        index
        for index, stmt in enumerate(statements)
        if isinstance(stmt, ast.If) and "request.method == 'POST'" in ast.unparse(stmt.test).replace('"', "'")
    )
    post_branch = statements[post_index]
    assert isinstance(post_branch, ast.If)
    assert isinstance(post_branch.body[-1], ast.Return)
    assert "build_workspace_context" not in _called_names(post_branch)
    before_post = ast.Module(body=statements[:post_index], type_ignores=[])
    assert "build_workspace_context" not in _called_names(before_post)
    after_post = ast.Module(body=statements[post_index + 1 :], type_ignores=[])
    builders = [name for name in _called_names(after_post) if name in {"build_workspace_context", "build_interim_notes_context"}]
    assert builders == ["build_workspace_context"]


def test_no_request_time_ddl_for_performance_interim_notes():
    offenders = []
    for path in APP.rglob("*.py"):
        for value in _strings(_tree(path)):
            if INTERIM_NOTES_DDL.search(value):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_no_replacement_temporary_commit_helper_in_the_readiness_modules():
    for path in (RUNTIME, P2, WORKSPACE):
        for name, function in _functions(path).items():
            if name.startswith("ensure_") and name.endswith("_table") and path != P2:
                assert not (_attribute_calls(function) & {"commit", "rollback"}), (path, name)
    for name, function in _functions(WORKSPACE).items():
        assert "commit" not in _attribute_calls(function), name
        assert "rollback" not in _attribute_calls(function), name


def test_business_operations_own_persistence_through_one_write_side_creator():
    functions = _functions(WORKSPACE)
    creator = functions[WRITE_SIDE_CREATOR]
    assert not (_attribute_calls(creator) & {"commit", "rollback"})
    for name in ("save_assignment_draft", "return_assignment_to_previous_level", "withdraw_assignment_submission"):
        assert WRITE_SIDE_CREATOR in _called_names(functions[name]), name
    assert "save_assignment_draft" in _called_names(functions["submit_assignment"])
    view = _functions(ROUTES)["performance_v2_phase3_assignment"]
    assert "commit" in _attribute_calls(view)
