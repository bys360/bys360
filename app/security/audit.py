"""BYS360 güvenlik denetim motoru.

Çalışma zamanı güvenlik bulgularını toplar, özetler ve loglar.
app.security.audit olarak import edilir.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class SecurityAuditFinding:
    level: str
    code: str
    message: str
    action: str


def _is_truthy(value: Any) -> bool:
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def collect_runtime_security_findings(config: Any) -> list[SecurityAuditFinding]:
    findings: list[SecurityAuditFinding] = []
    app_env = str(config.get('APP_ENV', 'development') or 'development').strip().lower()
    prod_like = app_env in {'production', 'staging', 'live', 'canli'}
    observability_like = app_env in {'production', 'staging', 'live', 'canli', 'pilot'}
    secret_key = str(config.get('SECRET_KEY', '') or '').strip()

    if not secret_key:
        findings.append(SecurityAuditFinding(
            level='critical' if prod_like else 'warning',
            code='missing_secret_key',
            message='SECRET_KEY tanimli degil.',
            action='Canliya cikmadan once guclu ve benzersiz SECRET_KEY tanimla.',
        ))
    elif len(secret_key) < 32:
        # Faz 12: Development ortamındaki kısa SECRET_KEY, canlı güvenlik warning'i
        # gibi sayılmasın. Production/staging için warning seviyesi korunur.
        findings.append(SecurityAuditFinding(
            level='warning' if prod_like else 'info',
            code='weak_secret_key',
            message='SECRET_KEY uzunlugu dusuk gorunuyor.',
            action='En az 32 karakterlik rastgele anahtar kullan.',
        ))

    if prod_like and not bool(config.get('SESSION_COOKIE_SECURE')):
        findings.append(SecurityAuditFinding(
            level='critical',
            code='session_cookie_not_secure',
            message='Production benzeri ortamda SESSION_COOKIE_SECURE kapali.',
            action='HTTPS arkasinda secure cookie ayarini aktif et.',
        ))

    if prod_like and not bool(config.get('REMEMBER_COOKIE_SECURE')):
        findings.append(SecurityAuditFinding(
            level='warning',
            code='remember_cookie_not_secure',
            message='REMEMBER_COOKIE_SECURE kapali.',
            action='Kalici oturum kullaniliyorsa secure cookie aktif et.',
        ))

    if int(config.get('MAX_CONTENT_LENGTH', 0) or 0) <= 0:
        findings.append(SecurityAuditFinding(
            level='critical',
            code='missing_upload_limit',
            message='MAX_CONTENT_LENGTH etkisiz gorunuyor.',
            action='Tum yukleme akislari icin boyut limiti tanimla.',
        ))
    elif int(config.get('MAX_CONTENT_LENGTH', 0) or 0) > 16 * 1024 * 1024:
        findings.append(SecurityAuditFinding(
            level='warning',
            code='wide_request_body_limit',
            message='MAX_CONTENT_LENGTH 16 MB ustunde: yukleme disi tum oturumlu isteklerin govde siniri da yukselir.',
            action='Buyuk dosyalar icin UPLOAD_MAX_CONTENT_LENGTH kullan; MAX_CONTENT_LENGTH degerini 16 MB veya altinda tut.',
        ))

    if not _is_truthy(config.get('REQUEST_GUARD_ENABLED', True)):
        findings.append(SecurityAuditFinding(
            level='warning',
            code='request_guard_disabled',
            message='Supheli istekleri filtreleyen request guard kapali.',
            action='Bot taramalarina karsi request guard katmanini acik tut.',
        ))

    if not _is_truthy(config.get('LOGIN_THROTTLE_ENABLED', True)):
        findings.append(SecurityAuditFinding(
            level='warning',
            code='login_throttle_disabled',
            message='Giris denemeleri icin ek IP/kimlik kilitlemesi kapali.',
            action='Brute force denemelerine karsi login throttle katmanini acik tut.',
        ))

    if not _is_truthy(config.get('WTF_CSRF_ENABLED', True)):
        findings.append(SecurityAuditFinding(
            level='critical',
            code='csrf_disabled',
            message='CSRF korumasi devre disi.',
            action='Flask-WTF CSRF korumasini aktif tut.',
        ))

    if int(config.get('WTF_CSRF_TIME_LIMIT', 0) or 0) < 900:
        findings.append(SecurityAuditFinding(
            level='info',
            code='csrf_short_ttl',
            message='CSRF zaman limiti oldukca dusuk; uzun formlarda sorun cikabilir.',
            action='Gerekirse sureyi gozden gecir.',
        ))

    if prod_like and not str(config.get('TCKN_ENCRYPTION_KEY', '') or '').strip():
        findings.append(SecurityAuditFinding(
            level='warning',
            code='missing_tckn_key',
            message='TCKN_ENCRYPTION_KEY tanimli degil.',
            action='Kimlik verisi alanlari kullaniliyorsa anahtar set et veya modulu kapat.',
        ))

    sentry_dsn = str(config.get('SENTRY_DSN', '') or '').strip().lower()
    sentry_required = _is_truthy(config.get('SENTRY_REQUIRED_IN_PRODUCTION', False))
    if observability_like and sentry_required and not sentry_dsn:
        findings.append(SecurityAuditFinding(
            level='critical',
            code='sentry_missing',
            message='SENTRY_DSN tanimli degil; canli hata izleme kapali.',
            action='Gercek Sentry DSN tanimla ve placeholder kullanma.',
        ))
    elif sentry_dsn and any(token in sentry_dsn for token in ('https://...@sentry.io/', 'sentry.io/...', 'your-public-key', 'project-id', 'change-me')):
        findings.append(SecurityAuditFinding(
            level='critical',
            code='sentry_placeholder',
            message='SENTRY_DSN placeholder deger gibi gorunuyor.',
            action='Gercek DSN gir veya canli zorunlulugu kapatma karari dokumante et.',
        ))

    db_uri = str(config.get('SQLALCHEMY_DATABASE_URI', '') or '').lower()
    if observability_like and db_uri.startswith('postgres') and 'sslmode=disable' in db_uri:
        findings.append(SecurityAuditFinding(
            level='critical',
            code='db_ssl_disabled',
            message='PostgreSQL baglantisinda sslmode=disable gorunuyor.',
            action='DATABASE_URL/SQLALCHEMY_DATABASE_URI icin sslmode=require veya daha guclu mod kullan.',
        ))

    csp_enabled = _is_truthy(config.get('CSP_ENABLED', True))
    csp_report_only = _is_truthy(config.get('CSP_REPORT_ONLY', True))
    if csp_enabled and csp_report_only:
        findings.append(SecurityAuditFinding(
            level='info',
            code='csp_report_only',
            message='CSP report-only modunda; ihlaller gorunur ama bloklanmaz.',
            action='Raporlari inceleyip politika olgunlastiktan sonra enforce moduna gec.',
        ))

    script_src = str(config.get('CSP_SCRIPT_SRC', '') or '')
    if observability_like and csp_enabled and "'unsafe-inline'" in script_src and not _is_truthy(config.get('CSP_ALLOW_UNSAFE_INLINE_SCRIPT', False)):
        findings.append(SecurityAuditFinding(
            level='critical',
            code='csp_unsafe_inline_script',
            message='CSP script-src icinde unsafe-inline var.',
            action='Nonce tabanli CSP kullan ve unsafe-inline script iznini kaldir.',
        ))

    if observability_like and csp_enabled and not _is_truthy(config.get('CSP_NONCE_ENABLED', False)):
        findings.append(SecurityAuditFinding(
            level='critical',
            code='csp_nonce_disabled',
            message='CSP nonce uretimi canli/pilot icin kapali.',
            action='CSP_NONCE_ENABLED=true yap.',
        ))

    return findings


def findings_to_dicts(findings: list[SecurityAuditFinding]) -> list[dict[str, str]]:
    return [asdict(item) for item in findings]


def build_security_audit_summary(config: Any) -> dict[str, Any]:
    findings = collect_runtime_security_findings(config)
    counts = {'critical': 0, 'warning': 0, 'info': 0}
    for finding in findings:
        counts[finding.level] = counts.get(finding.level, 0) + 1
    return {
        'counts': counts,
        'findings': findings_to_dicts(findings),
    }


def log_runtime_security_posture(app: Any) -> None:
    summary = build_security_audit_summary(app.config)
    counts = summary['counts']
    app.extensions['security_audit_summary'] = summary
    if counts.get('critical'):
        app.logger.warning(
            'Guvenlik ozeti | critical=%s warning=%s info=%s',
            counts.get('critical', 0),
            counts.get('warning', 0),
            counts.get('info', 0),
        )
    else:
        app.logger.info(
            'Guvenlik ozeti | critical=%s warning=%s info=%s',
            counts.get('critical', 0),
            counts.get('warning', 0),
            counts.get('info', 0),
        )