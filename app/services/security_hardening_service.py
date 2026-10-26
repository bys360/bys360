from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import current_app

import app.models as models
from app.extensions import db

logger = logging.getLogger(__name__)

try:
    from sqlalchemy import inspect as sa_inspect, text
except Exception:  # pragma: no cover
    logger.exception("BYS360 V6B guarded exception | file=app/services/security_hardening_service.py | line=27")
    text = None  # type: ignore[assignment]
    sa_inspect = None  # type: ignore[assignment]

"""BYS360 Faz 3 - Guvenlik ve yetki sertlestirme servisleri.

Bu servis, canliya cikis oncesi guvenlik ve yetki durumunu raporlamak icin tasarlandi.
Bilerek yikici degisiklik yapmaz; amaci eksikleri gorunur hale getirmek ve
kurumsal omurgayi bozmadan riskleri net gostermektir.
"""


User = getattr(models, "User", None)
MenuPermission = (
    getattr(models, "MenuPermission", None)
    or getattr(models, "UserMenuPermission", None)
    or getattr(models, "MenuPermissions", None)
)
ImportLog = getattr(models, "ImportLog", None)
AuditLog = (
    getattr(models, "AuditLog", None)
    or getattr(models, "ModuleAuditLog", None)
    or getattr(models, "SecurityAuditLog", None)
)


REQUIRED_ENV_FLAGS = {
    "SECRET_KEY": "required",
    "SESSION_COOKIE_HTTPONLY": "true",
    "REMEMBER_COOKIE_HTTPONLY": "true",
    "SESSION_COOKIE_SAMESITE": "Lax",
    "STRICT_ENV_VALIDATION": "true",
}

BOOLEAN_TRUE_VALUES = {"1", "true", "yes", "on"}
BOOLEAN_FALSE_VALUES = {"0", "false", "no", "off"}

PLACEHOLDER_MARKERS = (
    "changeme",
    "change-me",
    "example",
    "dummy",
    "secret",
    "test",
    "sample",
    "placeholder",
)

TCKN_PATTERNS = [
    r"\btckn\b",
    r"\btc_kimlik\b",
    r"\btc_no\b",
    r"kimlik\s*no",
    r"tc\s*kimlik",
    r"t\.c\.",
]

CAPTCHA_PATTERNS = [r"captcha", r"dogrulama", r"security verification"]
LOGIN_ATTEMPT_PATTERNS = [r"failed[_\s-]*login", r"login[_\s-]*attempt", r"hatali\s+giris", r"attempts?"]

SYSTEM_UNIT_NAMES = {"bys360"}
SYSTEM_ROLE_NAMES = {"admin"}


@dataclass(slots=True)
class Finding:
    category: str
    severity: str
    code: str
    title: str
    detail: str
    file_path: str = ""
    line_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
            "file_path": self.file_path,
            "line_hint": self.line_hint,
        }


@dataclass(slots=True)
class AuditReport:
    ok: bool = True
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)
        sev = (finding.severity or "").lower()
        if sev == "critical":
            self.critical_count += 1
            self.ok = False
        elif sev == "warning":
            self.warning_count += 1
        else:
            self.info_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "findings": [item.to_dict() for item in self.findings],
            "stats": self.stats,
            "notes": list(self.notes),
        }


def _safe(value: Any) -> str:
    return str(value or "").strip()


def _full_name(user: Any) -> str:
    full_name = _safe(getattr(user, "full_name", ""))
    if full_name:
        return full_name
    return f"{_safe(getattr(user, 'ad', ''))} {_safe(getattr(user, 'soyad', ''))}".strip()


def _project_root() -> Path:
    return Path(current_app.root_path).parent


def _read_env_file(env_path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not env_path.exists():
        return data
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def _looks_placeholder(value: str) -> bool:
    lowered = _safe(value).lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _iter_files(base: Path, suffixes: tuple[str, ...], skip_parts: tuple[str, ...] = ()) -> list[Path]:
    results: list[Path] = []
    if not base.exists():
        return results
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in suffixes:
            continue
        lowered_parts = {part.lower() for part in path.parts}
        if any(skip.lower() in lowered_parts for skip in skip_parts):
            continue
        results.append(path)
    return sorted(results)


def _scan_env(report: AuditReport, root_dir: Path) -> None:
    env_path = root_dir / ".env"
    env = _read_env_file(env_path)
    report.stats["env_file_exists"] = env_path.exists()
    if not env_path.exists():
        report.add(Finding(
            category="config",
            severity="warning",
            code="ENV_MISSING",
            title=".env bulunamadi",
            detail="Canli oncesi guvenlik bayraklarini dogrulamak icin .env dosyasi bulunamadi.",
            file_path=str(env_path),
        ))
        return

    for key, expectation in REQUIRED_ENV_FLAGS.items():
        raw = env.get(key, "")
        if expectation == "required":
            if not raw:
                report.add(Finding(
                    category="config",
                    severity="critical",
                    code=f"{key}_MISSING",
                    title=f"{key} eksik",
                    detail=f"{key} tanimli olmadan canliya cikmayin.",
                    file_path=str(env_path),
                ))
            elif _looks_placeholder(raw):
                report.add(Finding(
                    category="config",
                    severity="warning",
                    code=f"{key}_PLACEHOLDER",
                    title=f"{key} zayif veya ornek gorunuyor",
                    detail=f"{key} tanimli ama ornek/placeholder bir deger gibi gorunuyor; canli degeriyle degistirin.",
                    file_path=str(env_path),
                ))
            else:
                report.add(Finding(
                    category="config",
                    severity="info",
                    code=f"{key}_PRESENT",
                    title=f"{key} mevcut",
                    detail=f"{key} tanimli gorunuyor.",
                    file_path=str(env_path),
                ))
            continue

        lowered = raw.lower()
        if expectation.lower() == "true":
            if lowered not in BOOLEAN_TRUE_VALUES:
                sev = "warning" if raw else "critical"
                report.add(Finding(
                    category="config",
                    severity=sev,
                    code=f"{key}_NOT_TRUE",
                    title=f"{key} guvenli degil",
                    detail=f"{key} canli icin acik olmali / True olmali.",
                    file_path=str(env_path),
                ))
            else:
                report.add(Finding(
                    category="config",
                    severity="info",
                    code=f"{key}_OK",
                    title=f"{key} uygun",
                    detail=f"{key} canli icin uygun gorunuyor.",
                    file_path=str(env_path),
                ))
        elif key == "SESSION_COOKIE_SAMESITE":
            if lowered not in {"lax", "strict"}:
                report.add(Finding(
                    category="config",
                    severity="warning",
                    code="SESSION_COOKIE_SAMESITE_WEAK",
                    title="SESSION_COOKIE_SAMESITE zayif",
                    detail="SESSION_COOKIE_SAMESITE en az Lax olmali.",
                    file_path=str(env_path),
                ))
            else:
                report.add(Finding(
                    category="config",
                    severity="info",
                    code="SESSION_COOKIE_SAMESITE_OK",
                    title="SESSION_COOKIE_SAMESITE uygun",
                    detail=f"SESSION_COOKIE_SAMESITE={raw} gorunuyor.",
                    file_path=str(env_path),
                ))

    if env.get("TCKN_ENCRYPTION_KEY"):
        report.add(Finding(
            category="config",
            severity="info",
            code="TCKN_KEY_PRESENT",
            title="TCKN_ENCRYPTION_KEY mevcut",
            detail="Hassas kimlik alanlari icin sifreleme anahtari tanimli gorunuyor.",
            file_path=str(env_path),
        ))
    else:
        report.add(Finding(
            category="config",
            severity="warning",
            code="TCKN_KEY_MISSING",
            title="TCKN_ENCRYPTION_KEY eksik",
            detail="Projede TCKN veya hassas alanlar varsa sifreleme anahtari tanimli olmalidir.",
            file_path=str(env_path),
        ))


def _scan_csrf_templates(report: AuditReport, root_dir: Path) -> None:
    template_dir = root_dir / "app" / "templates"
    files = _iter_files(template_dir, (".html", ".jinja", ".j2"), skip_parts=("node_modules",))
    with_post = 0
    missing = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        if "<form" not in lowered:
            continue
        if 'method="post"' not in lowered and "method='post'" not in lowered and "method=post" not in lowered:
            continue
        with_post += 1
        if "csrf_token" in lowered or "hidden_tag()" in lowered or ".hidden_tag(" in lowered:
            continue
        missing += 1
        report.add(Finding(
            category="csrf",
            severity="warning",
            code="POST_FORM_NO_CSRF",
            title="POST formda CSRF izi yok",
            detail="Bu template icindeki POST formlarinda csrf_token veya hidden_tag izi gorunmuyor.",
            file_path=str(path.relative_to(root_dir)),
        ))
    report.stats["post_template_count"] = with_post
    report.stats["post_template_missing_csrf"] = missing
    if with_post and missing == 0:
        report.add(Finding(
            category="csrf",
            severity="info",
            code="POST_FORMS_CSRF_OK",
            title="Template CSRF taramasi temiz",
            detail=f"{with_post} adet POST template dosyasinda belirgin CSRF izi bulundu.",
        ))


def _scan_captcha(report: AuditReport, root_dir: Path) -> None:
    app_dir = root_dir / "app"
    files = _iter_files(app_dir, (".py", ".html", ".jinja", ".j2"), skip_parts=("migrations", "__pycache__"))
    captcha_hits = []
    attempt_hits = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        if any(re.search(pattern, lowered) for pattern in CAPTCHA_PATTERNS):
            captcha_hits.append(path)
        if any(re.search(pattern, lowered) for pattern in LOGIN_ATTEMPT_PATTERNS):
            attempt_hits.append(path)
    report.stats["captcha_file_hits"] = len(captcha_hits)
    report.stats["login_attempt_file_hits"] = len(attempt_hits)
    if captcha_hits and attempt_hits:
        report.add(Finding(
            category="auth",
            severity="info",
            code="CAPTCHA_FLOW_PRESENT",
            title="CAPTCHA ve giris sertlestirme izi bulundu",
            detail=f"CAPTCHA ile ilgili {len(captcha_hits)} ve hatali giris ile ilgili {len(attempt_hits)} dosya eslesti.",
        ))
    else:
        report.add(Finding(
            category="auth",
            severity="warning",
            code="CAPTCHA_FLOW_WEAK",
            title="CAPTCHA / hatali giris akisi belirsiz",
            detail="3 hatali giris sonrasi CAPTCHA akisini kod taramasinda net goremedim; manuel test edin.",
        ))


def _scan_tckn_exposure(report: AuditReport, root_dir: Path) -> None:
    app_dir = root_dir / "app"
    files = _iter_files(app_dir, (".py", ".html", ".jinja", ".j2", ".js"), skip_parts=("migrations", "__pycache__"))
    hits: list[dict[str, Any]] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for idx, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if any(re.search(pattern, lowered) for pattern in TCKN_PATTERNS):
                hits.append({
                    "file_path": str(path.relative_to(root_dir)),
                    "line": idx,
                    "snippet": line.strip()[:180],
                })
    report.stats["tckn_hit_count"] = len(hits)
    report.stats["tckn_hits"] = hits[:200]
    if hits:
        for hit in hits[:30]:
            report.add(Finding(
                category="kvkk",
                severity="warning",
                code="TCKN_TEXT_REVIEW",
                title="TCKN / TC kimlik izi bulundu",
                detail="Kod veya template icinde TCKN/TC ifadesi bulundu; sicil no yaklasimiyla uyumunu gozden gecirin.",
                file_path=hit["file_path"],
                line_hint=str(hit["line"]),
            ))
    else:
        report.add(Finding(
            category="kvkk",
            severity="info",
            code="TCKN_SCAN_CLEAN",
            title="TCKN taramasi temiz",
            detail="app/ altinda belirgin TCKN/TC kimlik izi gorunmedi.",
        ))


def _load_role_baseline(root_dir: Path) -> dict[str, Any]:
    path = root_dir / "config" / "security_role_baseline.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("BYS360 V6B guarded exception | file=app/services/security_hardening_service.py | line=409")
        return {}


def _db_table_exists(name: str) -> bool:
    if sa_inspect is None:
        return False
    inspector = sa_inspect(db.engine)
    return name in inspector.get_table_names()


def _scan_db_and_permissions(report: AuditReport, root_dir: Path) -> None:
    if not User:
        report.add(Finding(
            category="db",
            severity="warning",
            code="USER_MODEL_MISSING",
            title="User modeli bulunamadi",
            detail="Kullanici ve yetki denetimi icin User modeli import edilemedi.",
        ))
        return

    query = User.query
    if hasattr(User, "is_active"):
        query = query.filter(User.is_active == True)  # noqa: E712
    users = list(query.order_by(User.id.asc()).all())
    report.stats["active_user_count"] = len(users)

    role_counts: dict[str, int] = {}
    system_accounts = 0
    missing_role = 0
    missing_sicil = 0
    for user in users:
        role = _safe(getattr(user, "role", "")).lower() or "role_missing"
        role_counts[role] = role_counts.get(role, 0) + 1
        birim = _safe(getattr(user, "birim", "")).lower()
        ust_birim = _safe(getattr(user, "ust_birim", "")).lower()
        if role in SYSTEM_ROLE_NAMES or birim in SYSTEM_UNIT_NAMES or ust_birim in SYSTEM_UNIT_NAMES:
            system_accounts += 1
        if not _safe(getattr(user, "role", "")):
            missing_role += 1
        if not _safe(getattr(user, "sicil_no", "")):
            missing_sicil += 1

    report.stats["role_counts"] = role_counts
    report.stats["system_account_count"] = system_accounts
    report.stats["missing_role_count"] = missing_role
    report.stats["missing_sicil_count"] = missing_sicil

    if missing_role:
        report.add(Finding(
            category="authz",
            severity="critical",
            code="USER_ROLE_MISSING",
            title="Rolsuz aktif kullanici var",
            detail=f"{missing_role} aktif kullanicida role alani bos.",
        ))
    if missing_sicil:
        report.add(Finding(
            category="kvkk",
            severity="critical",
            code="USER_SICIL_MISSING",
            title="Sicil nosu eksik aktif kullanici var",
            detail=f"{missing_sicil} aktif kullanicida sicil numarasi bos.",
        ))

    if system_accounts:
        report.add(Finding(
            category="authz",
            severity="info",
            code="SYSTEM_ACCOUNT_PRESENT",
            title="Sistem hesabi ayrimi var",
            detail=f"{system_accounts} kayit sistem hesabi/teknik hesap gibi gorunuyor.",
        ))

    baseline = _load_role_baseline(root_dir)
    baseline_roles = baseline.get("roles", {}) if isinstance(baseline, dict) else {}
    report.stats["role_baseline_loaded"] = bool(baseline_roles)

    if MenuPermission:
        perm_rows = list(MenuPermission.query.all())
        report.stats["menu_permission_row_count"] = len(perm_rows)
        by_user: dict[int, dict[str, set[bool]]] = {}
        for row in perm_rows:
            user_id = getattr(row, "user_id", None)
            menu_key = _safe(getattr(row, "menu_key", ""))
            visible = bool(getattr(row, "is_visible", True))
            if user_id is None or not menu_key:
                continue
            by_user.setdefault(user_id, {}).setdefault(menu_key, set()).add(visible)

        conflict_count = 0
        for user_id, menus in by_user.items():
            for menu_key, values in menus.items():
                if len(values) > 1:
                    conflict_count += 1
                    report.add(Finding(
                        category="authz",
                        severity="warning",
                        code="MENU_PERMISSION_CONFLICT",
                        title="Ayni menu icin celiskili gorunurluk kaydi",
                        detail=f"user_id={user_id} icin {menu_key} hem gorunur hem gizli kayitlar iceriyor.",
                    ))
        report.stats["menu_permission_conflict_count"] = conflict_count

        if baseline_roles:
            user_by_id = {user.id: user for user in users}
            baseline_mismatch = 0
            for user_id, menus in by_user.items():
                user = user_by_id.get(user_id)
                if not user:
                    continue
                role = _safe(getattr(user, "role", "")).lower()
                required = set(baseline_roles.get(role, []))
                if not required:
                    continue
                visible_keys = {menu_key for menu_key, flags in menus.items() if True in flags}
                missing = sorted(required - visible_keys)
                if missing and visible_keys:
                    baseline_mismatch += 1
                    report.add(Finding(
                        category="authz",
                        severity="info",
                        code="ROLE_BASELINE_REVIEW",
                        title="Rol bazli menu baseline inceleme notu",
                        detail=f"{_full_name(user)} ({role}) icin baseline menulerinden eksik gorunen anahtarlar: {', '.join(missing[:10])}",
                    ))
            report.stats["role_baseline_review_count"] = baseline_mismatch
    else:
        report.add(Finding(
            category="authz",
            severity="warning",
            code="MENU_PERMISSION_MODEL_MISSING",
            title="Menu permission modeli bulunamadi",
            detail="Kisi bazli menu gorunurlugu denetimi icin MenuPermission modeli import edilemedi.",
        ))

    audit_tables = []
    if ImportLog:
        audit_tables.append("import_logs")
    if AuditLog:
        audit_tables.append(getattr(AuditLog, "__tablename__", "audit_logs"))
    for table_name in ("import_logs", "audit_logs", "module_audit_logs"):
        if _db_table_exists(table_name):
            audit_tables.append(table_name)
    deduped = sorted(set(audit_tables))
    report.stats["audit_tables"] = deduped
    if deduped:
        report.add(Finding(
            category="audit",
            severity="info",
            code="AUDIT_TABLE_PRESENT",
            title="Audit/import tablo izi bulundu",
            detail=f"Bulunan log/audit tablolari: {', '.join(deduped)}",
        ))
    else:
        report.add(Finding(
            category="audit",
            severity="warning",
            code="AUDIT_TABLE_MISSING",
            title="Audit/log tablosu izi zayif",
            detail="import_logs veya audit_logs tablolari gorulemedi; denetim izi tarafini gozden gecirin.",
        ))


def run_security_and_access_audit() -> AuditReport:
    report = AuditReport()
    root_dir = _project_root()
    report.stats["project_root"] = str(root_dir)

    _scan_env(report, root_dir)
    _scan_csrf_templates(report, root_dir)
    _scan_captcha(report, root_dir)
    _scan_tckn_exposure(report, root_dir)
    _scan_db_and_permissions(report, root_dir)

    if report.critical_count == 0:
        report.notes.append("Kritik bulgu gorunmuyor; warning ve info kayitlarini da yine de gozden gecirin.")
    else:
        report.notes.append("Kritik bulgular kapanmadan tam canliya cikmayin.")

    return report

def build_security_posture_snapshot() -> dict[str, Any]:
    """UI dostu ozet guvenlik pozisyonu dondurur.

    Savunmaci tasarim: herhangi bir ortam degiskeni veya servis eksiginde bile
    ekranlarin dusmemesi icin her alan varsayilan degerle dondurulur.
    """
    report = run_security_and_access_audit()
    upload_extensions = current_app.config.get("ALLOWED_UPLOAD_EXTENSIONS", "")
    if isinstance(upload_extensions, str):
        normalized_extensions = [x.strip().lower() for x in upload_extensions.split(",") if x.strip()]
    elif isinstance(upload_extensions, (list, tuple, set)):
        normalized_extensions = [str(x).strip().lower() for x in upload_extensions if str(x).strip()]
    else:
        normalized_extensions = []

    return {
        "ok": bool(getattr(report, "ok", False)),
        "critical_count": int(getattr(report, "critical_count", 0) or 0),
        "warning_count": int(getattr(report, "warning_count", 0) or 0),
        "info_count": int(getattr(report, "info_count", 0) or 0),
        "note_count": len(getattr(report, "notes", []) or []),
        "allowed_upload_extensions": normalized_extensions,
        "max_upload_mb": round(int(current_app.config.get("UPLOAD_MAX_CONTENT_LENGTH") or current_app.config.get("MAX_CONTENT_LENGTH", 16 * 1024 * 1024)) / (1024 * 1024), 2),
        "session_cookie_secure": bool(current_app.config.get("SESSION_COOKIE_SECURE", False)),
        "session_cookie_httponly": bool(current_app.config.get("SESSION_COOKIE_HTTPONLY", True)),
        "remember_cookie_secure": bool(current_app.config.get("REMEMBER_COOKIE_SECURE", False)),
        "remember_cookie_httponly": bool(current_app.config.get("REMEMBER_COOKIE_HTTPONLY", True)),
        "same_site": str(current_app.config.get("SESSION_COOKIE_SAMESITE", "Lax")),
        "strict_env_validation": bool(current_app.config.get("STRICT_ENV_VALIDATION", False)),
    }
