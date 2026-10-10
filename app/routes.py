
"""BYS360 ana blueprint omurgası.

Faz 8 ile bu dosya artık gerçek bir toplayıcı/omurga dosyası oldu: ana
blueprint, sağlık uçları, context processor'lar ve modüler route ailelerinin
kayıt importları burada tutuluyor. Büyük gövdeler ilgili handler modüllerinde.
"""
from __future__ import annotations

import ipaddress

from flask import abort, current_app, jsonify, request, send_from_directory
from flask_login import current_user, login_required

from app.config import (
    REMOVED_ROUTE_ENDPOINT_PREFIXES,
    REMOVED_ROUTE_PATH_PREFIXES,
    REMOVED_SCOPE_COMPAT_ENDPOINTS,
    is_removed,
)
from app.main_handlers.account_handlers import (
    account,
    account_change_password,
    account_change_photo,
    account_security_setup,
    settings_page,
)
from app.main_handlers.auth_handlers import forgot_password, login, logout, setup_admin
from app.main_handlers.comparison_handlers import (
    my_performance_comparison,
    team_performance_comparison_history,
)
from app.main_handlers.dashboard_handlers import dashboard, db_check
from app.main_handlers.public_handlers import (
    home as _home_handler,
    index as _index_handler,
    kunye as _kunye_handler,
)
from app.route_registry import main_bp
from app.view_helpers import (
    enforce_first_login_security_flow_redirect,
    get_global_risk_banner_context,
    get_menu_visibility_context,
    get_route_helper_context,
)


# BYS360_LOGOUT_FORCE_CLEAR_V2_15_12_BEGIN
@main_bp.after_app_request
def bys360_logout_no_store_authenticated_pages(response):
    try:
        endpoint = str(getattr(request, "endpoint", "") or "")
        path = str(getattr(request, "path", "") or "")
        content_type = str(response.headers.get("Content-Type", "") or "")
        wants_html = "text/html" in content_type or "text/html" in str(request.headers.get("Accept", "") or "")
        sensitive_path = (
            path in {"/", "/home", "/login", "/logout"}
            or path.startswith((
                "/account", "/admin", "/dashboard", "/feedback", "/hr-management",
                "/messages", "/performance", "/performans", "/personnel", "/portal",
                "/settings", "/support", "/survey", "/surveys",
            ))
        )
        if endpoint != "static" and (wants_html or sensitive_path) and (sensitive_path or current_user.is_authenticated):
            response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers.setdefault("X-BYS360-Logout-Fix", "V2.15.12")
    except Exception:
        current_app.logger.debug("BYS360 logout no-store header uygulanamadı", exc_info=True)
    return response
# BYS360_LOGOUT_FORCE_CLEAR_V2_15_12_END

@main_bp.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "bys360"}), 200


@main_bp.get("/readyz")
def readyz():
    schema_errors = list(current_app.extensions.get("schema_check_errors", []) or [])
    payload = {
        "status": "ready" if not schema_errors else "degraded",
        "service": "bys360",
        "app_env": current_app.config.get("APP_ENV", "development"),
        "schema_error_count": len(schema_errors),
    }
    return jsonify(payload), (200 if not schema_errors else 503)

# BYS360_PROFILE_PHOTO_VISIBILITY_V2_17_73_BEGIN
@main_bp.get("/uploads/profile_photos/<path:filename>")
@login_required
def bys360_profile_photo_file(filename: str):
    """Profil fotoğraflarını kırık görsel oluşturmadan güvenli biçimde sunar."""
    import os
    from pathlib import Path

    from werkzeug.utils import secure_filename

    safe_name = secure_filename(Path(filename or "").name)
    if not safe_name:
        abort(404)

    from app.security.private_uploads import legacy_static_upload_path, private_upload_path

    # B2-F06: yeni fotoğraflar static dışındaki özel depoda; eski konumlar geri dönüş olarak okunur.
    roots = [private_upload_path("profile_photos").resolve()]
    static_profile_dir = legacy_static_upload_path("profile_photos").resolve()
    roots.append(static_profile_dir)

    configured_upload_root = current_app.config.get("UPLOAD_FOLDER") or os.getenv("UPLOAD_FOLDER")
    if configured_upload_root:
        upload_root = Path(str(configured_upload_root)).resolve()
        roots.append((upload_root / "profile_photos").resolve())
        roots.append((upload_root / "uploads" / "profile_photos").resolve())

    for root in roots:
        candidate = (root / safe_name).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            response = send_from_directory(str(root), safe_name, as_attachment=False, conditional=True)
            response.headers.setdefault("Cache-Control", "private, max-age=3600")
            return response

    default_dir = (Path(current_app.root_path) / "static" / "img").resolve()
    response = send_from_directory(str(default_dir), "default-avatar.svg", as_attachment=False, conditional=True)
    response.headers.setdefault("Cache-Control", "private, max-age=600")
    return response
# BYS360_PROFILE_PHOTO_VISIBILITY_V2_17_73_END


def _bys360_release_identity() -> dict[str, str | None]:
    """BYS360 DEFECT Z: reads THIS running process's own bundled
    CANDIDATE_READY.json (written by prepare_bys360_candidate.ps1, verified
    and carried across promotion by cutover_bys360_candidate.ps1) to expose
    the release this specific process was actually promoted from. Every
    promoted version lives at the same fixed C:\\bys360\\project path, so
    process/PID/path metadata alone can never distinguish WHICH release's
    code is currently loaded -- this is the one place that can. Absent in
    local/dev environments not managed by that pipeline; never raises.

    BYS360 PRODUCTION RELEASE-IDENTITY HOTFIX #2: reads with "utf-8-sig",
    not "utf-8". A real production CANDIDATE_READY.json was confirmed to
    start with a UTF-8 byte-order-mark (EF BB BF) -- prepare_bys360_
    candidate.ps1's receipt writer used PowerShell's "-Encoding UTF8"
    parameter, which Windows PowerShell 5.1 (what production runs) writes
    WITH a BOM. json.loads(receipt_path.read_text(encoding="utf-8")) then
    decodes that BOM as a literal U+FEFF character prefixed onto the JSON
    text, which json.loads rejects (JSONDecodeError: "Unexpected UTF-8
    BOM"), silently forcing source_sha/migration_head to null even for a
    fully valid, correctly-promoted candidate. "utf-8-sig" transparently
    strips a leading BOM if present and decodes identically to "utf-8"
    when absent, so both the still-existing BOM-prefixed receipts (already
    written by the old writer) and newly-written BOM-less receipts (see
    prepare_bys360_candidate.ps1's Write-Utf8NoBomFile) parse correctly."""
    import json
    from pathlib import Path

    receipt_path = Path(current_app.root_path).parent / "CANDIDATE_READY.json"
    try:
        data = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"source_sha": None, "migration_head": None}
    return {
        "source_sha": data.get("SOURCE_SHA"),
        "migration_head": data.get("MIGRATION_HEAD"),
    }


def _bys360_request_is_from_loopback() -> bool:
    """BYS360 DEFECT AF: True only for a caller connected directly over the
    raw TCP loopback interface -- e.g. cutover_bys360_candidate.ps1's own
    curl.exe call to http://127.0.0.1:$AppPort during a local cutover run.

    BYS360 PRODUCTION RELEASE-IDENTITY HOTFIX #2: reads the RAW socket peer
    address from Werkzeug ProxyFix's own actual environ contract. Verified
    directly against the installed werkzeug (3.1.8) source and confirmed
    live: ProxyFix.__call__ stores the pre-rewrite originals as a SINGLE
    dict at environ["werkzeug.proxy_fix.orig"] (keys "REMOTE_ADDR",
    "wsgi.url_scheme", "HTTP_HOST", "SERVER_NAME", "SERVER_PORT",
    "SCRIPT_NAME") -- the flat "werkzeug.proxy_fix.orig_remote_addr" key
    this function previously read was REMOVED from Werkzeug in 1.0 (see
    werkzeug's own changelog in proxy_fix.py) and has never existed in any
    version this app has run under. Because that key never exists, the
    previous `environ.get("werkzeug.proxy_fix.orig_remote_addr",
    request.remote_addr)` call silently always evaluated its *default* --
    request.remote_addr -- which is exactly what ProxyFix REWRITES from an
    operator-configured number of trusted X-Forwarded-For hops (x_for=1
    here). A live probe with PROXY_FIX_ENABLED genuinely active proved
    this concretely: a request with a real raw peer of 203.0.113.5 and a
    forged "X-Forwarded-For: 127.0.0.1" header resulted in the previous
    code reading "127.0.0.1" -- the previous implementation's claimed
    raw-peer protection against exactly this spoof was never actually in
    effect. (The pre-existing regression test for this scenario passed
    only because it enabled ProxyFix via monkeypatch.setenv, which cannot
    affect config.py's Config.PROXY_FIX_ENABLED -- a class attribute
    evaluated once at first import of the module, not re-read per request
    or per env change; see tests/security/test_https_scheme_and_hsts_
    hardening.py's monkeypatch.setattr(Config, ...) pattern for the
    correct way to genuinely enable it in a test. That test therefore
    never actually exercised ProxyFix at all.)

    Trust rule: if environ["werkzeug.proxy_fix.orig"] exists (ProxyFix is
    genuinely wrapping this request), its own "REMOTE_ADDR" is the ONLY
    trusted raw-peer source -- request.remote_addr is deliberately never
    consulted in that branch, even if the dict's REMOTE_ADDR is missing or
    malformed (fails closed to non-loopback rather than silently trusting
    a value ProxyFix may have already rewritten from client-controlled
    headers). Only when ProxyFix is genuinely absent/disabled -- no orig
    dict in the environ at all -- is request.remote_addr itself the raw,
    unforgeable socket peer, safe to evaluate directly. Under no
    circumstance can X-Forwarded-For alone convert a genuinely non-
    loopback raw connection into a trusted loopback one.

    Canonical IP parsing (ipaddress.ip_address.is_loopback), not a fixed
    string set -- a real production cutover's self-curl to
    http://127.0.0.1:$AppPort observed its own raw peer as the
    IPv4-mapped-IPv6 form "::ffff:127.0.0.1" (a legitimate representation
    of a genuine IPv4 loopback connection on a dual-stack Windows socket),
    which a literal {"127.0.0.1", "::1"} membership check does not
    recognize, silently forcing source_sha/migration_head to null even for
    a genuine loopback caller. An IPv4-mapped IPv6 address is unwrapped to its
    embedded IPv4 form before the loopback check so it is judged by the
    same rule as a direct IPv4 connection; every other address (public,
    private/LAN, link-local) is correctly still non-loopback, and a
    malformed/empty peer value fails closed to False, never raises."""
    proxy_fix_orig = request.environ.get("werkzeug.proxy_fix.orig")
    if proxy_fix_orig is None:
        raw_peer = request.remote_addr
    else:
        raw_peer = proxy_fix_orig.get("REMOTE_ADDR") if isinstance(proxy_fix_orig, dict) else None
    peer = str(raw_peer or "").strip().split("%", 1)[0]
    if not peer:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return bool(addr.is_loopback)


@main_bp.get("/versionz")
def versionz():
    runtime_manifest = current_app.extensions.get("runtime_route_manifest") or {}
    schema_errors = list(current_app.extensions.get("schema_check_errors", []) or [])
    payload = {
        "service": "bys360",
        "app_env": current_app.config.get("APP_ENV", "development"),
        "route_count": len(runtime_manifest) if isinstance(runtime_manifest, dict) else 0,
        "schema_error_count": len(schema_errors),
    }
    # BYS360 DEFECT AF: source_sha/migration_head identify the exact
    # deployed git commit and Alembic revision -- real, if low-severity,
    # deployment-fingerprinting information. /versionz has no @login_
    # required (matching /healthz and /readyz, an intentional, pre-existing
    # design this fix does not change), so these two fields are exposed
    # only to callers connecting from the loopback interface -- exactly
    # what cutover_bys360_candidate.ps1's own Test-ReleaseIdentityBinding
    # needs (it always curls http://127.0.0.1:$AppPort directly) and
    # nothing more. Every other field above remains public, unchanged.
    if _bys360_request_is_from_loopback():
        release = _bys360_release_identity()
        payload["source_sha"] = release["source_sha"]
        payload["migration_head"] = release["migration_head"]
    else:
        payload["source_sha"] = None
        payload["migration_head"] = None
    return jsonify(payload), 200


@main_bp.before_app_request
def block_removed_module_routes():
    endpoint = str(getattr(request, "endpoint", "") or "")
    path = str(getattr(request, "path", "") or "")

    if endpoint in REMOVED_SCOPE_COMPAT_ENDPOINTS:
        return None

    for module_name, prefixes in REMOVED_ROUTE_ENDPOINT_PREFIXES.items():
        if not is_removed(module_name):
            continue
        for prefix in prefixes:
            if endpoint == prefix or endpoint.startswith(prefix):
                abort(404)

    for module_name, prefixes in REMOVED_ROUTE_PATH_PREFIXES.items():
        if not is_removed(module_name):
            continue
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                abort(404)


@main_bp.app_context_processor
def inject_menu_visibility():
    return get_menu_visibility_context()


@main_bp.app_context_processor
def inject_global_risk_banner():
    return get_global_risk_banner_context()


@main_bp.app_context_processor
def inject_route_helpers():
    return get_route_helper_context()


def enforce_first_login_security_flow():
    return enforce_first_login_security_flow_redirect()


main = main_bp  # BYS360_PHASE10_MAIN_BLUEPRINT_ALIAS
@main_bp.route("/")
def index():
    return _index_handler()


@main_bp.route("/home")
@login_required
def home():
    return _home_handler()


# Modüler ana blueprint route aileleri
from app.account import routes as _account_routes  # noqa: E402,F401
from app.admin import routes as _admin_routes  # noqa: E402,F401
from app.ai import routes as _ai_routes  # noqa: E402,F401
from app.auth import routes as _auth_routes  # noqa: E402,F401
from app.communication import (  # noqa: E402 - deferred import (staged facade/route-registration architecture)
    feedback_routes as _feedback_routes,  # noqa: E402,F401
    routes as _communication_routes,  # noqa: E402,F401
    user_feedback_routes as _bys360_user_feedback_routes,  # noqa: E402,F401
)
from app.dashboard import routes as _dashboard_routes  # noqa: E402,F401
from app.institutional import routes as _institutional_routes  # noqa: E402,F401
from app.performance import routes as _performance_routes  # noqa: E402,F401

# BYS360_CORPORATE_PORTAL_V1_ROUTE_IMPORT
from app.portal import routes as _portal_routes  # noqa: E402,F401
from app.settings_center import routes as _settings_center_routes  # noqa: E402,F401
from app.support import routes as _support_routes  # noqa: E402,F401

__all__ = [
    "main_bp",
    "healthz",
    "readyz",
    "versionz",
    "index",
    "home",
    "login",
    "forgot_password",
    "logout",
    "setup_admin",
    "dashboard",
    "settings_page",
    "account",
    "account_change_photo",
    "account_security_setup",
    "account_change_password",
    "db_check",
    "my_performance_comparison",
    "team_performance_comparison_history",
]

@main_bp.route("/kunye")
def kunye():
    return _kunye_handler()

# BYS360_PHASE10_REPORTS_ROUTE_IMPORT_AFTER_MAIN
try:
    from app.performance import (
        process_engine_phase10_reports_routes as _phase10_reports_routes,  # noqa: F401,E402
    )
except ImportError:  # route import should never break app startup silently
    raise

# BYS360_PHASE12_PRESIDENT_APPROVALS_CARD_ROUTE_IMPORT
try:
    from app.performance import (
        president_low_score_card_routes as _bys360_phase12_president_card_routes,  # noqa: F401,E402
    )
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/routes.py)")
# /BYS360_PHASE12_PRESIDENT_APPROVALS_CARD_ROUTE_IMPORT

# BYS360_SP2F_STRATEGIC_PERFORMANCE_SIDEBAR_ROUTE_IMPORT
try:
    from app.performance import sp1_sidebar_routes as _sp2f_sp1_sidebar_routes  # noqa: F401,E402
except Exception:
    # Route uyumluluğu uygulama açılışını bozmasın; gate scripti ayrıca doğrular.
    __import__("logging").getLogger(__name__).exception("BYS360 kalite denetimi: sessiz except/pass yakalandi (app/routes.py:184)")
# /BYS360_SP2F_STRATEGIC_PERFORMANCE_SIDEBAR_ROUTE_IMPORT

# BYS360_MOBILE_PWA_FAZ2_V1_ROUTES_BEGIN
@main_bp.get("/manifest.webmanifest")
def bys360_pwa_manifest():
    from flask import current_app, make_response, send_from_directory
    assert current_app.static_folder is not None, "BYS360 app must have a configured static folder"
    response = make_response(send_from_directory(current_app.static_folder, "pwa/manifest.webmanifest", mimetype="application/manifest+json"))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@main_bp.get("/bys360-sw.js")
def bys360_pwa_service_worker():
    from flask import current_app, make_response, send_from_directory
    assert current_app.static_folder is not None, "BYS360 app must have a configured static folder"
    response = make_response(send_from_directory(current_app.static_folder, "pwa/bys360-sw.js", mimetype="application/javascript"))
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response
# BYS360_MOBILE_PWA_FAZ2_V1_ROUTES_END


# BYS360 V2 route bootstrap tarafindan yukleniyor; app.routes importu kapatildi

# BYS360_CORPORATE_INFORMATION_CENTER_V3_ROUTE_IMPORT
try:
    from app.communication import (
        corporate_information_center_routes as _bys360_corporate_information_center_routes,  # noqa: F401,E402
    )
except Exception:
    __import__("logging").getLogger(__name__).exception("BYS360 Kurumsal Bilgilendirme Merkezi route import failed")
# /BYS360_CORPORATE_INFORMATION_CENTER_V3_ROUTE_IMPORT


# BYS360_A5_P2D4_LIVE_SCOPE_PORTAL_PREFIX_ANCHOR_START
# Static contract anchor: /portal
# Portal prefix canl? kapsam/karantina s?zle?mesinde a??k?a izlenir.
# BYS360_A5_P2D4_LIVE_SCOPE_PORTAL_PREFIX_ANCHOR_END
# BYS360 Dosya Merkezi route kayıtları
# Bu import, app/file_center/routes.py içindeki main_bp route dekoratörlerini uygulamaya bağlar.
from app.file_center import routes as _file_center_routes  # noqa: F401,E402

