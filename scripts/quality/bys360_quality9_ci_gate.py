from __future__ import annotations

import argparse
import ast
import configparser
import json
import re
import shlex
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

QUALITY9_MAX_APP_PRINT = 0
DEFAULT_QUALITY9_MAX_APP_BROAD_EXCEPT = 2064
TARGET_KEYWORDS = ("auth", "session", "permission", "security")
SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "backups", "backup",
    "reports", "logs", "releases", "overlays", "archive",
}


@dataclass
class GateFinding:
    code: str
    path: str
    detail: str
    line: int | None = None


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def iter_py(root: Path, base: Path) -> list[Path]:
    paths: list[Path] = []
    if base.is_file() and base.suffix == ".py":
        return [base]
    if not base.exists():
        return []
    for path in base.rglob("*.py"):
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            parts = path.parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        paths.append(path)
    return paths


def _is_exception_handler(node: ast.ExceptHandler) -> bool:
    if node.type is None:
        return False
    if isinstance(node.type, ast.Name) and node.type.id == "Exception":
        return True
    if isinstance(node.type, ast.Tuple):
        return any(isinstance(item, ast.Name) and item.id == "Exception" for item in node.type.elts)
    return False


def _uses_name(node: ast.AST, name: str) -> bool:
    return any(isinstance(child, ast.Name) and child.id == name for child in ast.walk(node))


def _has_logging_or_raise(node: ast.ExceptHandler) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Raise):
            return True
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr in {"exception", "error", "warning", "critical", "info", "debug"}:
                return True
            if isinstance(func, ast.Name) and func.id.lower() in {"abort", "flash"}:
                return True
    return False


def scan_python(root: Path) -> tuple[dict[str, int], list[GateFinding]]:
    totals = {"python_files": 0, "syntax_errors": 0, "app_print_calls": 0, "app_broad_excepts": 0}
    findings: list[GateFinding] = []
    for path in iter_py(root, root / "app"):
        totals["python_files"] += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except SyntaxError as exc:
            totals["syntax_errors"] += 1
            findings.append(GateFinding("syntax_error", rel(path, root), exc.msg, exc.lineno))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                totals["app_print_calls"] += 1
            if isinstance(node, ast.ExceptHandler) and _is_exception_handler(node):
                totals["app_broad_excepts"] += 1
                if node.name is None and _uses_name(node, "exc"):
                    findings.append(GateFinding("undefined_exc_in_except", rel(path, root), "except bloğunda exc adı kullanılıyor ama yakalanmıyor", node.lineno))
                target_path = rel(path, root).lower()
                if any(keyword in target_path for keyword in TARGET_KEYWORDS) and not _has_logging_or_raise(node):
                    findings.append(GateFinding("silent_security_except", rel(path, root), "auth/session/permission/security hattında logsuz except Exception", node.lineno))
    return totals, findings


def workflow_run_commands(text: str) -> list[str]:
    """Return executable YAML ``run`` commands, excluding comments and metadata."""
    lines = text.splitlines()
    commands: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        match = re.match(r"^(?P<indent>[ \t]*)run:\s*(?P<value>.*)$", line)
        if not match:
            index += 1
            continue

        base_indent = len(match.group("indent").expandtabs(8))
        value = match.group("value").strip()
        if value.startswith(("|", ">")):
            folded = value.startswith(">")
            block_lines: list[str] = []
            index += 1
            while index < len(lines):
                candidate = lines[index]
                stripped = candidate.strip()
                if not stripped:
                    index += 1
                    continue
                indent = len(candidate) - len(candidate.lstrip(" \t"))
                if indent <= base_indent:
                    break
                if not stripped.startswith("#"):
                    block_lines.append(stripped)
                index += 1
            if folded and block_lines:
                commands.append(" ".join(block_lines))
            else:
                commands.extend(block_lines)
            continue

        if value and not value.startswith("#"):
            commands.append(value)
        index += 1

    return commands


def _command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, comments=True, posix=True)
    except ValueError:
        return []


def _normalized_path(value: str) -> str:
    return value.strip("'\"").replace("\\", "/").lstrip("./")


def _option_values(tokens: list[str], option: str) -> list[str]:
    values: list[str] = []
    prefix = f"{option}="
    for index, token in enumerate(tokens):
        if token == option and index + 1 < len(tokens):
            values.append(tokens[index + 1])
        elif token.startswith(prefix):
            values.append(token[len(prefix) :])
    return values


def _option_sequence(tokens: list[str], option: str) -> list[str]:
    try:
        start = tokens.index(option) + 1
    except ValueError:
        return []

    values: list[str] = []
    for token in tokens[start:]:
        if token.startswith("-"):
            break
        values.append(token)
    return values


def _is_pytest_command(tokens: list[str]) -> bool:
    normalized = [_normalized_path(token) for token in tokens]
    if any(token.rsplit("/", 1)[-1] in {"pytest", "pytest.exe"} for token in normalized):
        return True
    return any(tokens[index : index + 2] == ["-m", "pytest"] for index in range(len(tokens) - 1))


def _runs_script(tokens: list[str], expected_path: str) -> bool:
    expected = _normalized_path(expected_path)
    return any(_normalized_path(token) == expected for token in tokens)


def _has_test_scope(tokens: list[str], expected_scope: str) -> bool:
    expected = _normalized_path(expected_scope).rstrip("/")
    return any(_normalized_path(token).rstrip("/") == expected for token in tokens)


def _has_option_value(tokens: list[str], option: str, expected: str) -> bool:
    normalized_expected = _normalized_path(expected)
    return any(_normalized_path(value) == normalized_expected for value in _option_values(tokens, option))


def check_workflow(root: Path, max_broad_except: int) -> list[GateFinding]:
    findings: list[GateFinding] = []
    path = root / ".github" / "workflows" / "bys360-ci.yml"
    if not path.exists():
        return [GateFinding("missing_ci_workflow", rel(path, root), "CI workflow bulunamadı")]
    text = path.read_text(encoding="utf-8", errors="ignore")
    commands = workflow_run_commands(text)
    tokenized = [_command_tokens(command) for command in commands]
    pytest_commands = [tokens for tokens in tokenized if _is_pytest_command(tokens)]

    ci_safe_commands = [
        tokens
        for tokens in pytest_commands
        if _has_test_scope(tokens, "tests/quality")
        and "ci_safe" in _option_values(tokens, "-m")
    ]
    if not ci_safe_commands:
        findings.append(GateFinding("pytest_not_enforced", rel(path, root), "CI içinde ci_safe pytest kapısı zorunlu"))
    if not any(_has_option_value(tokens, "--cov", "app") for tokens in ci_safe_commands):
        findings.append(
            GateFinding(
                "coverage_measurement_not_enforced",
                rel(path, root),
                "ci_safe pytest adımı uygulama coverage ölçümünü --cov=app ile başlatmalı",
            )
        )

    coverage_xml_commands = [
        tokens
        for tokens in pytest_commands
        if "--cov-append" in tokens
        and _has_option_value(tokens, "--cov", "app")
        and _has_option_value(tokens, "--cov-report", "xml:reports/quality/coverage.xml")
    ]
    if not coverage_xml_commands:
        findings.append(
            GateFinding(
                "coverage_xml_not_enforced",
                rel(path, root),
                "CI birleşik app coverage verisini reports/quality/coverage.xml olarak üretmeli",
            )
        )

    ratchet_commands = [
        tokens
        for tokens in tokenized
        if _runs_script(tokens, "scripts/quality/bys360_coverage_ratchet.py")
        and _has_option_value(tokens, "--coverage-xml", "reports/quality/coverage.xml")
        and _has_option_value(tokens, "--baseline", "reports/quality/coverage_baseline.json")
    ]
    if not ratchet_commands:
        findings.append(
            GateFinding(
                "coverage_ratchet_not_enforced",
                rel(path, root),
                "Coverage ratchet doğru XML ve baseline yollarıyla çağrılmalı",
            )
        )
    if not (root / "scripts" / "quality" / "bys360_coverage_ratchet.py").is_file():
        findings.append(
            GateFinding(
                "missing_coverage_ratchet_script",
                "scripts/quality/bys360_coverage_ratchet.py",
                "CI tarafından çağrılan coverage ratchet scripti bulunamadı",
            )
        )
    if not (root / "reports" / "quality" / "coverage_baseline.json").is_file():
        findings.append(
            GateFinding(
                "missing_coverage_baseline",
                "reports/quality/coverage_baseline.json",
                "Coverage ratchet baseline dosyası bulunamadı",
            )
        )

    audit_commands = [
        tokens
        for tokens in tokenized
        if _runs_script(tokens, "scripts/quality/bys360_ops_audit.py")
    ]
    broad_except_values = [
        value
        for tokens in audit_commands
        for value in _option_values(tokens, "--max-broad-except")
    ]
    if not broad_except_values:
        findings.append(GateFinding("missing_broad_except_threshold", rel(path, root), "CI broad-except eşiği bulunamadı"))
    else:
        try:
            threshold = int(broad_except_values[0])
        except ValueError:
            findings.append(
                GateFinding(
                    "invalid_broad_except_threshold",
                    rel(path, root),
                    f"CI broad-except eşiği sayı değil: {broad_except_values[0]}",
                )
            )
        else:
            if threshold == 3500:
                findings.append(
                    GateFinding(
                        "broad_except_threshold_too_loose",
                        rel(path, root),
                        "3500 eşiği kalite güvencesi üretmez",
                    )
                )
            elif threshold > max_broad_except:
                findings.append(
                    GateFinding(
                        "broad_except_threshold_above_quality9",
                        rel(path, root),
                        f"Eşik {threshold}; kalite hedefi {max_broad_except}",
                    )
                )

    required_sources = {"app", "config.py", "wsgi.py", "run.py"}
    if not any(
        required_sources.issubset({_normalized_path(value) for value in _option_sequence(tokens, "--source-paths")})
        for tokens in audit_commands
    ):
        findings.append(GateFinding("audit_scope_not_app", rel(path, root), "CI bütçesi yaşayan uygulama kodu için app/config/wsgi/run kapsamına bağlanmalı"))
    return findings


def _attribute_path(node: ast.AST) -> tuple[str, ...]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return tuple(reversed(parts))


def _node_mentions_ci_safe(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and "ci_safe" in child.id.lower():
            return True
        if isinstance(child, ast.Attribute) and child.attr.lower() == "ci_safe":
            return True
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and child.value.strip().lower() == "ci_safe"
        ):
            return True
    return False


def _module_declares_ci_safe_pytestmark(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in targets):
            continue
        value = node.value
        if value is None:
            continue
        candidates = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
        if any(_attribute_path(candidate) == ("pytest", "mark", "ci_safe") for candidate in candidates):
            return True
    return False


def check_ci_safe_hook(root: Path) -> list[GateFinding]:
    findings: list[GateFinding] = []
    path = root / "tests" / "conftest.py"
    if not path.exists():
        return [GateFinding("missing_tests_conftest", rel(path, root), "tests/conftest.py bulunamadı")]
    text = path.read_text(encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [
            GateFinding(
                "invalid_tests_conftest",
                rel(path, root),
                exc.msg,
                exc.lineno,
            )
        ]

    if any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "pytest_collection_modifyitems"
        for node in ast.walk(tree)
    ):
        findings.append(
            GateFinding(
                "ci_safe_custom_collection_hook_present",
                rel(path, root),
                "ci_safe seçimi path tabanlı collection hook yerine pytest marker ifadesine bırakılmalı",
            )
        )
    if any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_marker"
        and any(_node_mentions_ci_safe(argument) for argument in node.args)
        for node in ast.walk(tree)
    ):
        findings.append(
            GateFinding(
                "ci_safe_scope_too_broad",
                rel(path, root),
                "Tüm testleri otomatik ci_safe işaretleyen davranış kapatılmalı",
            )
        )

    pytest_config = root / "pytest.ini"
    parser = configparser.ConfigParser(interpolation=None)
    if not pytest_config.exists():
        findings.append(
            GateFinding(
                "missing_pytest_config",
                rel(pytest_config, root),
                "pytest.ini bulunamadı",
            )
        )
    else:
        try:
            parser.read(pytest_config, encoding="utf-8")
            markers = parser.get("pytest", "markers", fallback="")
        except (configparser.Error, OSError) as exc:
            findings.append(
                GateFinding(
                    "invalid_pytest_config",
                    rel(pytest_config, root),
                    str(exc),
                )
            )
        else:
            if not re.search(r"(?m)^\s*ci_safe\s*:", markers):
                findings.append(
                    GateFinding(
                        "ci_safe_marker_not_registered",
                        rel(pytest_config, root),
                        "pytest.ini içinde ci_safe marker kaydı bulunamadı",
                    )
                )

    quality_test = root / "tests" / "quality" / "test_quality9_ci_safe_contract.py"
    if not quality_test.exists():
        findings.append(GateFinding("missing_quality9_ci_safe_tests", rel(quality_test, root), "Deterministik ci_safe kalite testi bulunamadı"))
    else:
        try:
            quality_tree = ast.parse(
                quality_test.read_text(encoding="utf-8"),
                filename=str(quality_test),
            )
        except SyntaxError as exc:
            findings.append(
                GateFinding(
                    "invalid_quality9_ci_safe_tests",
                    rel(quality_test, root),
                    exc.msg,
                    exc.lineno,
                )
            )
        else:
            if not _module_declares_ci_safe_pytestmark(quality_tree):
                findings.append(
                    GateFinding(
                        "quality9_tests_not_ci_safe",
                        rel(quality_test, root),
                        "Quality 9 sözleşme testleri pytest.mark.ci_safe ile işaretlenmeli",
                    )
                )
    return findings

def main() -> int:
    parser = argparse.ArgumentParser(description="BYS360 Quality 9 CI contract gate")
    parser.add_argument("--root", default=None)
    parser.add_argument("--project-root", dest="project_root", default=None, help="Backward-compatible alias for --root")
    parser.add_argument("--report", default="reports/quality/BYS360_QUALITY9_CI_GATE_REPORT.json")
    parser.add_argument("--max-broad-except", type=int, default=DEFAULT_QUALITY9_MAX_APP_BROAD_EXCEPT)
    args = parser.parse_args()

    root_value = args.root or args.project_root or "."
    root = Path(root_value).resolve()
    max_broad_except = int(args.max_broad_except)

    totals, findings = scan_python(root)
    findings.extend(check_workflow(root, max_broad_except))
    findings.extend(check_ci_safe_hook(root))

    if totals["syntax_errors"]:
        findings.append(GateFinding("syntax_errors_present", "app", f"Syntax hatası: {totals['syntax_errors']}"))
    if totals["app_print_calls"] > QUALITY9_MAX_APP_PRINT:
        findings.append(GateFinding("app_print_budget_exceeded", "app", f"print() {totals['app_print_calls']} > {QUALITY9_MAX_APP_PRINT}"))
    if totals["app_broad_excepts"] > max_broad_except:
        findings.append(GateFinding("app_broad_except_budget_exceeded", "app", f"except Exception {totals['app_broad_excepts']} > {max_broad_except}"))

    report = {
        "package": "BYS360_QUALITY9_CI_SAFE_SCOPE_HOTFIX_V10",
        "generated_at": datetime.now(UTC).isoformat(),
        "quality9_targets": {
            "app_print_calls_max": QUALITY9_MAX_APP_PRINT,
            "app_broad_except_max": max_broad_except,
            "ci_pytest_marker": "ci_safe",
            "security_silent_except_allowed": 0,
        },
        "totals": totals,
        "ok": not findings,
        "findings": [asdict(item) for item in findings],
    }
    report_path = Path(args.report)
    out = report_path if report_path.is_absolute() else root / report_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "totals": totals, "finding_count": len(findings), "report": str(out)}, ensure_ascii=False))
    if findings:
        for finding in findings[:30]:
            print(f"BYS360_QUALITY9_FAIL={finding.code} {finding.path}:{finding.line or ''} {finding.detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
