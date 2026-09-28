"""Scan app/ for broad exception handlers that return a fallback value (read-only).

usage: python scripts/quality/bys360_silent_fallback_scan.py [--out PATH]
Records every `except Exception` / bare / BaseException handler with its enclosing function,
the constant(s) it returns and whether it logs; classifies conservatively. The scan summary
is the "scan_summary" of reports/quality/BYS360_CRITICAL_SILENT_FALLBACKS_V1.json, whose
"reviewed" section records the hand review of the security- and decision-relevant hits.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

WT = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else None
AUTHZ_NAME = re.compile(r"^_?(can|is|has|user_can|user_has|allow|allowed|permit|permitted|check|ensure|assert|require|may)_|"
                        r"(permission|access|authoriz|scope|visible|visibility|_owner|allowed)", re.I)
DATA_NAME = re.compile(r"(count|total|pending|approval|score|average|avg|metric|summary|stats|kpi|low_score|publish|"
                       r"result|report|list_|rows|queue|overdue|remaining|balance|quota)", re.I)
CRITICAL_PATH = re.compile(r"(performance|personnel|hr_|president|approval|low_score|scorecard|evaluation|file_center|"
                           r"survey|security|auth|permission|scope|visibility|menu|settings)", re.I)
BROAD = {"Exception", "BaseException"}


def _broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = []
    if isinstance(handler.type, ast.Tuple):
        names = [ast.unparse(e) for e in handler.type.elts]
    else:
        names = [ast.unparse(handler.type)]
    return any(n.split(".")[-1] in BROAD for n in names)


def _returned(handler: ast.ExceptHandler) -> list[str]:
    values = []
    for node in ast.walk(handler):
        if isinstance(node, ast.Return):
            if node.value is None:
                values.append("None")
            elif isinstance(node.value, ast.Constant):
                values.append(repr(node.value.value))
            elif isinstance(node.value, ast.List | ast.Dict | ast.Tuple | ast.Set) and not getattr(node.value, "elts", getattr(node.value, "keys", [1])):
                values.append(ast.unparse(node.value))
            else:
                values.append("expr:" + ast.unparse(node.value)[:60])
    return values


def _logs(handler: ast.ExceptHandler) -> bool:
    text = ast.unparse(handler)
    return bool(re.search(r"\.(exception|error|warning|critical)\(|log_|record_security_event|logger\.", text))


class Scanner(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.stack: list[str] = []
        self.rows: list[dict] = []

    def _func(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _func
    visit_AsyncFunctionDef = _func

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if _broad(node) and self.stack:
            func = self.stack[-1]
            returns = _returned(node)
            self.rows.append({"file": self.path, "line": node.lineno, "function": func, "returns": returns,
                              "logs": _logs(node), "reraises": any(isinstance(n, ast.Raise) for n in ast.walk(node))})
        self.generic_visit(node)


rows = []
for path in sorted((WT / "app").rglob("*.py")):
    rel = str(path.relative_to(WT)).replace("\\", "/")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except SyntaxError:
        continue
    s = Scanner(rel)
    s.visit(tree)
    rows.extend(s.rows)

for r in rows:
    rets = r["returns"]
    authz = bool(AUTHZ_NAME.search(r["function"]))
    critical = bool(CRITICAL_PATH.search(r["file"]) or CRITICAL_PATH.search(r["function"]))
    if r["reraises"] and not rets:
        cls = "SAFE_RERAISE"
    elif authz and "True" in rets:
        cls = "AUTHORIZATION_RISK"
    elif authz and rets and all(v in {"False", "None", "[]", "set()", "{}", "()"} for v in rets):
        cls = "SAFE_FAIL_CLOSED"
    elif DATA_NAME.search(r["function"]) and critical and any(v in {"0", "0.0", "[]", "{}", "None", "()"} for v in rets):
        cls = "DATA_CORRECTNESS_RISK_CANDIDATE"
    elif not r["logs"] and not rets:
        cls = "OBSERVABILITY_DEBT"
    else:
        cls = "SAFE_PRESENTATION_FALLBACK_OR_UNCLASSIFIED"
    r["classification"] = cls

summary = {"broad_handlers": len(rows), "by_classification": dict(Counter(r["classification"] for r in rows))}
if OUT is not None:
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(summary, indent=1))
