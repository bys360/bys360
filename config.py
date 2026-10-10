import ipaddress
import logging
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

# BYS360_CANLI_SAGLAMLASTIRMA_FAZ1_8_DOTENV_FALLBACK_V2
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(dotenv_path=None, override: bool = False, **_kwargs):  # type: ignore[misc]
        """python-dotenv yoksa uygulamayı düşürmeyen minimum .env okuyucu."""
        path = dotenv_path or ".env"
        try:
            with open(path, encoding="utf-8-sig") as handle:
                lines = handle.readlines()
        except FileNotFoundError:
            return False
        except OSError:
            return False

        loaded = False
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            if override or key not in os.environ:
                os.environ[key] = value
                loaded = True
        return loaded


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DOTENV_PATH = Path(BASE_DIR) / '.env'
load_dotenv(DOTENV_PATH)


def str_to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _host_is_local_or_private(hostname: str | None) -> bool:
    host = (hostname or '').strip().lower()
    if not host:
        return False
    if host in {'localhost', '127.0.0.1', '::1'}:
        return True
    try:
        ip_value = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip_value.is_private or ip_value.is_loopback or ip_value.is_link_local)


def _default_secure_cookie(app_base_url: str, preferred_url_scheme: str) -> bool:
    """Acik env degeri yokken cookie Secure varsayilani.

    BYS360_SEC3A_A1_SCHEME_COOKIE_CONSISTENCY_V1: karar artik yalnizca ham
    APP_BASE_URL semasina degil, cozumlenmis PREFERRED_URL_SCHEME'e (etkili
    dis HTTPS sinyali -- explicit env override > APP_BASE_URL semasi, bkz.
    _resolve_preferred_url_scheme) bakar. Boylece PREFERRED_URL_SCHEME=https
    override edildiginde varsayilan sessizce eski/yerel APP_BASE_URL
    semasinda takili kalmaz. Host local/private ise (mevcut dev/test akisi)
    Secure her zaman False kalir -- aksi halde tarayici Secure cerezi
    yalnizca HTTPS baglantida gonderecegi icin oturum fiilen kirilir.
    """
    hostname = urlparse((app_base_url or '').strip()).hostname
    if _host_is_local_or_private(hostname):
        return False
    return (preferred_url_scheme or '').strip().lower() == 'https'


def _resolve_secure_cookie(
    raw_value: str | None,
    app_env: str,
    app_base_url: str,
    preferred_url_scheme: str,
    *,
    cookie_name: str = 'SESSION_COOKIE_SECURE',
) -> bool:
    """SESSION_COOKIE_SECURE / REMEMBER_COOKIE_SECURE icin tek cozumleme sozlesmesi.

    Sira: acik env degeri > etkili dis HTTPS semasiyla (PREFERRED_URL_SCHEME,
    sadece ham APP_BASE_URL degil) tutarli guvenli varsayilan.

    - Acik 'true' istenmis olsa bile, host local/private ise ya da etkili dis
      sema https degilse yok sayilir (Secure cerez boyle bir baglantida
      tarayicidan hic donmeyecegi icin oturumu kirar) ve bu durum loglanir.
    - BYS360_SEC3B_A1_COOKIE_FAIL_FAST_V1: acik 'false' -- production/staging
      APP_ENV'de VE etkili dis sema HTTPS (host public) iken -- artik
      operatorun "bilincli tercihi" sayilip sessizce/yalnizca bir warning ile
      gecirilmez. Bu kombinasyon her zaman bir RuntimeError ile config.py'nin
      import edilmesini durdurur (once bir logger.warning ile isaretlenir,
      sonra ayni bilgiyle RuntimeError firlatilir) -- SECRET_KEY guard'i ve
      asagidaki PREFERRED_URL_SCHEME/APP_BASE_URL sema-celiskisi guard'i ile
      ayni fail-fast usluptadir. Boylece config.py, uygulama hic olusturul-
      madan (bare `import config` seviyesinde) bile bagimsiz/self-sufficient
      olarak bu riskli kombinasyonu reddeder; production/staging disi
      (development/testing) ya da local/private host icin bu dal ASLA
      tetiklenmez.
      Not: app/security/startup_audit.validate_live_security_defaults da
      ayni iki alani (SESSION_COOKIE_SECURE/REMEMBER_COOKIE_SECURE) semadan
      bagimsiz olarak production/staging'de True olmaya zorlar, ama SADECE
      gercek bir Flask app create_app() ile olusturuldugunda (factory_
      bootstrap.run_preflight_checks adiminda) calisir. Bu fonksiyondaki
      fail-fast onun YERINE GECMEZ -- ikisi farkli katmanlarda ayni sonuca
      varan bagimsiz/tekrarlayan (defense-in-depth) guard'lardir: burasi
      "etkili sema https iken false" gibi daha dar/erken bir alt kumeyi
      config.py import zamaninda yakalar; validate_live_security_defaults
      ise semadan bagimsiz olarak (ornegin gercekten http olan bir production
      dagitiminda bile) Secure cerez zorunlulugunu app olusturma zamaninda
      genel olarak denetler. Biri diger kontrolu "ekarte etmez"; ikisi de
      kalir.
    - Acik deger yoksa sonuc _default_secure_cookie() ile belirlenir.
    """
    parsed = urlparse((app_base_url or '').strip())
    hostname = parsed.hostname
    host_is_local = _host_is_local_or_private(hostname)
    scheme_is_https = (preferred_url_scheme or '').strip().lower() == 'https'
    effective_https = scheme_is_https and not host_is_local

    raw = raw_value.strip() if isinstance(raw_value, str) else raw_value
    has_explicit = bool(raw)
    if has_explicit:
        explicit_value = str_to_bool(raw, False)
        if explicit_value and not effective_https:
            logger.warning(
                "%s=true acikca istenmis ama etkili dis sema/host bunu desteklemiyor "
                "(host=%s, PREFERRED_URL_SCHEME=%s); Secure cerez boyle bir "
                "baglantida tarayicidan hic donmeyip oturumu kirabileceginden bu "
                "deger guvenli sekilde False'a dusuruldu.",
                cookie_name, hostname or app_base_url, preferred_url_scheme,
            )
            return False
        if not explicit_value and effective_https and app_env in {'production', 'staging'}:
            conflict_msg = (
                f"{cookie_name}=false acikca ayarlanmis; ancak etkili dis sema HTTPS "
                f"(PREFERRED_URL_SCHEME={preferred_url_scheme}, host={hostname or app_base_url}) "
                f"ve APP_ENV={app_env}. Production/staging'de etkili dis sema HTTPS "
                f"oldugunda {cookie_name} True olmak zorundadir; cerez calinmasi / oturum "
                "ele gecirme riski tasidigindan bu kombinasyon artik operatorun bilincli "
                "tercihi olarak bile sessizce kabul edilmiyor."
            )
            logger.warning(conflict_msg)
            raise RuntimeError(
                "Production/staging ortaminda etkili dis sema HTTPS iken "
                f"{cookie_name}=false celisir, uygulama baslatilamaz: " + conflict_msg +
                f" Guvenli acilis icin {cookie_name} degiskenini kaldirin ya da true yapin."
            )
        return explicit_value

    return _default_secure_cookie(app_base_url, preferred_url_scheme)


def _resolve_preferred_url_scheme(raw_value: str | None, app_base_url: str) -> str:
    """Acik PREFERRED_URL_SCHEME > APP_BASE_URL semasi > guvenli varsayilan (http).

    Explicit env degeri gecerli (http/https) degilse yok sayilir ve bir sonraki
    kaynaga (APP_BASE_URL semasi) dusulur; o da cozulemezse Flask'in kendi
    varsayilanina esdeger, guvenli/iddiasiz 'http' donulur -- boylece hicbir
    zaman dogrulanmamis bir HTTPS iddiasi uretilmez.
    """
    explicit = (raw_value or '').strip().lower()
    if explicit in {'http', 'https'}:
        return explicit
    base_scheme = (urlparse((app_base_url or '').strip()).scheme or '').strip().lower()
    if base_scheme in {'http', 'https'}:
        return base_scheme
    return 'http'


def _preferred_url_scheme_conflicts_with_app_base_url(raw_preferred_value: str | None, app_base_url: str) -> bool:
    """PREFERRED_URL_SCHEME'in acik env degeri, APP_BASE_URL'in kendi semasindan farkli mi?

    Yalnizca acik bir override varsa anlamlidir: override yoksa
    _resolve_preferred_url_scheme() zaten APP_BASE_URL semasine duser, bu
    yuzden trivial olarak celisme olamaz. Her iki yon de (APP_BASE_URL=http
    + PREFERRED_URL_SCHEME=https, ya da tersi) celiski sayilir.
    """
    explicit = (raw_preferred_value or '').strip().lower()
    if explicit not in {'http', 'https'}:
        return False
    base_scheme = (urlparse((app_base_url or '').strip()).scheme or '').strip().lower()
    if base_scheme not in {'http', 'https'}:
        return False
    return explicit != base_scheme


_LOCAL_TRUSTED_HOST_DEFAULTS: tuple[str, ...] = ('localhost', '127.0.0.1', '::1')


def _split_trusted_hosts_env(raw_value: str | None) -> list[str]:
    """Virgulle ayrilmis TRUSTED_HOSTS env degerini temiz bir listeye cevirir."""
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(',') if item.strip()]


def _resolve_trusted_hosts(raw_value: str | None, app_base_url: str, app_env: str) -> list[str]:
    """Flask'in yerlesik ``app.config['TRUSTED_HOSTS']`` Host-header dogrulamasi
    (bkz. ``werkzeug.sansio.utils.get_host`` / ``host_is_trusted`` -- Flask 3.1,
    her istekte ``create_url_adapter()`` icinde otomatik cagrilir, ek bir
    route_support.py kancasi GEREKMEZ) icin kullanilacak allowlist'i cozer.

    Sozlesme:
      * Kanonik host -- ``app_base_url``'in kendi hostname'i -- HER ZAMAN
        listenin ilk/temel ogesidir. Bu, tutarli tek bir "gercek" host
        kaynagini garanti eder ve dondurulen liste ASLA bos olmaz (bos/None
        bir TRUSTED_HOSTS, Werkzeug'de "tum host'lara guven" -- fiilen
        wildcard'a esdeger -- anlamina gelir, bkz. host_is_trusted:
        ``if not trusted_list: return True``).
      * Acik ``TRUSTED_HOSTS`` env degeri (virgulle ayrilmis) varsa ek host
        olarak eklenir. '*' girdisi production/staging'de KESINLIKLE
        reddedilir (RuntimeError) -- Werkzeug'de bos/None disinda '*' diye
        ozel bir "hepsine izin ver" degeri yoktur, boyle bir girdi sadece
        literal '*' host adiyla eslesir ve operatorun aslinda korumayi
        tamamen kapatmak istedigine isaret eder; bu yanlis anlamayi
        production'da erken ve gurultulu sekilde reddediyoruz.
      * Acik TRUSTED_HOSTS, kanonik host'u icermiyorsa (operator hatasi/
        eksik konfigurasyon) sessizce gecilmez -- bir logger.warning
        yazilir VE kanonik host yine de listeye eklenerek tutarlilik
        otomatik saglanir (APP_BASE_URL bu modulun tek guven kokudur).
      * Dev/test ortaminda (``app_env in {'development','test','testing'}``
        VEYA kanonik host zaten ``_host_is_local_or_private`` ise)
        localhost/127.0.0.1/::1 otomatik eklenir -- boylece yerel gelistirme
        akislari (Flask test client'in varsayilan Host'u dahil) kirilmaz.
      * Port: girdiler yalnizca host-bazlidir. ``urlparse(...).hostname``
        zaten portu ayiklar, bu yuzden kanonik host hicbir zaman port
        icermez; Werkzeug'un kendi ``host_is_trusted()``'i da hem gelen
        Host basligindaki hem de trusted-list girdilerindeki portu
        (varsa) karsilastirmadan once atar -- bu yuzden operator yanlislikla
        ``host:port`` yapistirirsa bile kirilmaz, port basitce yok sayilir.
      * IDN/punycode: BILINCLI olarak burada AYRICA normalize edilmez.
        Werkzeug'un ``host_is_trusted()``'i her trusted-list girdisini
        karsilastirmadan once kendisi ``.encode('idna')`` ile kodlar (bkz.
        werkzeug/sansio/utils.py); ayrica gelen Host basligi zaten ASCII/
        punycode olmak ZORUNDADIR (Werkzeug, ASCII-disi karakter iceren bir
        Host basligini `_host_re` regex'i ile daha karsilastirmadan once
        gecersiz sayar). Yani hem Unicode hem de onceden punycode'lanmis
        TRUSTED_HOSTS girdileri ayni sonucu verir; burada tekrar/celiskili
        bir IDNA katmani eklemek gereksiz karmasikliktir.
    """
    canonical_host = (urlparse((app_base_url or '').strip()).hostname or '').strip().lower()
    explicit_entries = _split_trusted_hosts_env(raw_value)

    if app_env in {'production', 'staging'}:
        for entry in explicit_entries:
            if entry == '*':
                raise RuntimeError(
                    "Production/staging ortaminda TRUSTED_HOSTS icinde '*' (wildcard) "
                    "kullanilamaz -- bu Flask'in Host header dogrulamasini fiilen "
                    "devre disi birakip host-header poisoning / cache poisoning "
                    "riskini geri getirir. TRUSTED_HOSTS'u somut, virgulle ayrilmis "
                    "host adlariyla sinirlayin (ornek: 'bys360.canakkaletarihialan."
                    "gov.tr')."
                )

    resolved: list[str] = []
    _seen_lower: set[str] = set()

    def _add(host: str) -> None:
        host = (host or '').strip()
        if host and host.lower() not in _seen_lower:
            _seen_lower.add(host.lower())
            resolved.append(host)

    if canonical_host:
        _add(canonical_host)

    if explicit_entries and canonical_host:
        normalized_explicit = set()
        for entry in explicit_entries:
            normalized = entry.strip().lower()
            normalized = normalized[1:] if normalized.startswith('.') else normalized
            normalized_explicit.add(normalized)
        already_covered = any(
            canonical_host == entry or canonical_host.endswith('.' + entry)
            for entry in normalized_explicit
        )
        if not already_covered:
            logger.warning(
                "TRUSTED_HOSTS acikca ayarlanmis ('%s') ama APP_BASE_URL'in kendi "
                "host'unu ('%s') icermiyor; tutarliligi bozmamak icin APP_BASE_URL "
                "host'u allowlist'e otomatik eklendi. Operator TRUSTED_HOSTS'u "
                "APP_BASE_URL ile tutarli olacak sekilde guncellemelidir.",
                raw_value, canonical_host,
            )

    for entry in explicit_entries:
        _add(entry)

    is_dev_or_test_env = app_env in {'development', 'test', 'testing'}
    if is_dev_or_test_env or _host_is_local_or_private(canonical_host or None):
        for local_host in _LOCAL_TRUSTED_HOST_DEFAULTS:
            _add(local_host)

    if not resolved and app_env in {'production', 'staging'}:
        raise RuntimeError(
            "TRUSTED_HOSTS icin gecerli bir kanonik host belirlenemedi (APP_BASE_URL="
            f"'{app_base_url}'); production/staging ortaminda bos/None TRUSTED_HOSTS "
            "Flask'in tum Host basliklarina guvenmesi (wildcard'a esdeger) anlamina "
            "gelir ve kabul edilemez. Gecerli bir APP_BASE_URL (host iceren) "
            "ayarlayin."
        )

    return resolved


def _coerce_positive_int(raw_value: str | None, fallback: int) -> int:
    try:
        value = int(str(raw_value or '').strip())
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def _coerce_float(raw_value: str | None, fallback: float) -> float:
    try:
        return float(str(raw_value or '').strip())
    except (TypeError, ValueError):
        return fallback


def _append_db_sslmode(db_url: str, app_env: str) -> str:
    """Production/staging PostgreSQL baglantilarinda SSL'i guvenli varsayilan yap.

    Eski paketlerde DATABASE_URL icinde SSL kapalı bağlantı parametresi kalabildigi icin sadece
    eksik degeri tamamlamak yeterli degildi. Canli/staging ortaminda uzak
    PostgreSQL kullaniliyorsa `disable` degeri, bilincli olarak
    DB_ALLOW_SSL_DISABLE=true verilmedikce `require` ile ezilir.
    """
    raw = (db_url or '').strip()
    if not raw:
        return raw
    parsed = urlparse(raw)
    scheme = (parsed.scheme or '').lower()
    if not scheme.startswith('postgres'):
        return raw
    if app_env not in {'production', 'staging'}:
        return raw
    if _host_is_local_or_private(parsed.hostname):
        return raw

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    requested_sslmode = (os.getenv('DB_SSLMODE', 'require').strip() or 'require').lower()
    allow_disable = str_to_bool(os.getenv('DB_ALLOW_SSL_DISABLE'), False)
    current_sslmode = (query.get('sslmode') or '').strip().lower()

    if current_sslmode in {'', 'disable'} and not allow_disable:
        query['sslmode'] = requested_sslmode
    elif current_sslmode == 'disable' and allow_disable:
        query['sslmode'] = 'disable'
    return urlunparse(parsed._replace(query=urlencode(query)))

def _normalize_runtime_redis_url(raw_url: str | None, app_env: str) -> tuple[str, str | None]:
    """Bare-metal canlıda docker hostname redis://redis:6379 ayarını sessizce bozmasın.

    Docker/compose kullanılıyorsa BYS360_DEPLOYMENT_MODE=docker verilerek bu hostname
    bilinçli biçimde korunabilir. Aksi halde çözümlenemeyen docker hostname'i güvenli
    şekilde file/memory fallback'e düşürülür.
    """
    try:
        from app.services.redis_config_guard import sanitize_redis_url
        return sanitize_redis_url(
            raw_url,
            app_env=app_env,
            deployment_mode=os.getenv('BYS360_DEPLOYMENT_MODE', ''),
        )
    except Exception as exc:
        logger.exception("BYS360 critical exception captured in config.py", exc_info=exc)
        return (raw_url or '').strip(), None


def _is_sqlite_url(db_url: str) -> bool:
    return (db_url or '').strip().lower().startswith('sqlite:')


class Config:
    APP_ENV = os.getenv('APP_ENV', 'development').strip().lower()
    APP_BASE_URL = os.getenv('APP_BASE_URL', 'http://127.0.0.1:8000').strip()
    PREFERRED_URL_SCHEME = _resolve_preferred_url_scheme(os.getenv('PREFERRED_URL_SCHEME'), APP_BASE_URL)

    # BYS360_SEC3A_A1_SCHEME_COOKIE_CONSISTENCY_V1
    # PREFERRED_URL_SCHEME'in acik env override'i APP_BASE_URL'in kendi
    # semasindan farkliysa (ornek: APP_BASE_URL=http://... ama acik
    # PREFERRED_URL_SCHEME=https, ya da tersi), HSTS ve cookie Secure
    # kararlarinin hangi semaya gore verildigi belirsizlesir. Production/
    # staging'de -- host local/private degilse, yani gercek bir canli
    # dagitim soz konusuysa -- bu SECRET_KEY ile ayni uslupta fail-fast'e
    # donusturulur. Local/private host'larda (dev/test akisi, ornegin bu
    # dosyadaki HSTS testlerinin PREFERRED_URL_SCHEME'i app.config uzerinden
    # gecici olarak override etmesi) ve APP_ENV='testing'/'development'
    # oldugu surece asla tetiklenmez.
    _preferred_scheme_raw_override = os.getenv('PREFERRED_URL_SCHEME')
    _preferred_scheme_conflict = _preferred_url_scheme_conflicts_with_app_base_url(
        _preferred_scheme_raw_override, APP_BASE_URL
    )
    _preferred_scheme_conflict_host = urlparse(APP_BASE_URL).hostname
    if _preferred_scheme_conflict and not _host_is_local_or_private(_preferred_scheme_conflict_host):
        _preferred_scheme_conflict_msg = (
            f"PREFERRED_URL_SCHEME (acik deger: '{_preferred_scheme_raw_override}') "
            f"APP_BASE_URL semasindan ('{urlparse(APP_BASE_URL).scheme}') farkli; HSTS ve "
            "cookie Secure kararlari hangi semanin 'gercek' oldugu konusunda ayrisir."
        )
        if APP_ENV in {'production', 'staging'}:
            logger.warning(_preferred_scheme_conflict_msg)
            raise RuntimeError(
                "Production/staging ortaminda PREFERRED_URL_SCHEME ile APP_BASE_URL "
                "semasi celisemez: " + _preferred_scheme_conflict_msg + " APP_BASE_URL'i "
                "gercek dis semaya gore guncelleyin ya da PREFERRED_URL_SCHEME "
                "override'ini kaldirin."
            )

    # BYS360_SEC3C_A1_PRODUCTION_HTTPS_FAIL_FAST_V1
    # Yukaridaki celiski guard'i (hemen ustte) YALNIZCA acik bir
    # PREFERRED_URL_SCHEME override'i APP_BASE_URL semasiyla CELISIYORSA
    # tetiklenir. Gercek acik nokta bu degildi: production/staging'de
    # APP_BASE_URL=http://... (hicbir acik PREFERRED_URL_SCHEME override'i
    # YOK, host public) -> _resolve_preferred_url_scheme() sessizce APP_BASE_
    # URL'in kendi semasina (http) duser, yukaridaki celiski guard'i devre
    # disi kalir (celisecek bir "acik deger" hic yok ki), SECRET_KEY/cookie
    # guard'lari da bu durumu yakalamaz -> bare `import config` exit=0 ile
    # basariyla tamamlanir ve production canli bir HTTP dagitimini onaysiz
    # kabul eder. BYS360'in production sozlesmesi HER ZAMAN HTTPS olmak
    # zorunda oldugundan bu artik kabul edilemez.
    #
    # Bu guard yukaridaki PREFERRED_URL_SCHEME/APP_BASE_URL celiski guard'i
    # ile CAKISMAZ, onu TAMAMLAR (ikisi de "production'da guvenilir olmayan
    # dis sema" kok nedenini farkli acidan yakalayan, kasitli olarak
    # ortusen/defense-in-depth iki kontroldur):
    #   - Yukaridaki guard: yalnizca acik bir PREFERRED_URL_SCHEME override'i
    #     APP_BASE_URL semasindan FARKLIYSA calisir (iki yonlu celiski).
    #     Class body'de bu guard AYNI PREFERRED_URL_SCHEME/APP_BASE_URL
    #     celiskisini asagidaki guard'dan ONCE degerlendirdigi icin, celisen
    #     bir override oldugunda (ornegin APP_BASE_URL=https + override=http,
    #     ki bu durumda cozumlenen PREFERRED_URL_SCHEME de 'http' olur ve
    #     asagidaki guard da teorik olarak tetiklenebilirdi) import HER ZAMAN
    #     once burada durur -- asagidaki guard'a hic ulasilmaz. Bu beklenen
    #     ve zararsizdir; hangisinin "once" ateslendigi onemli degildir,
    #     ikisi de ayni sonuca (RuntimeError, boot durur) varir.
    #   - Asagidaki guard (bu guard): cozumlenen PREFERRED_URL_SCHEME'in
    #     KENDISI (acik bir override olsun ya da OLMASIN -- ozellikle
    #     override HIC yokken APP_BASE_URL'in kendi http semasina sessizce
    #     dusuldugu, yukaridaki guard'in hic devreye giremeyecegi durumu)
    #     https DEGILSE, production/staging + non-local/private host'ta
    #     devreye girer. Bu, yukaridaki guard'in kapsam disi biraktigi tam
    #     bosluktur.
    #   - Local/private host'ta (dev/test akislari, _host_is_local_or_private)
    #     bu guard ASLA tetiklenmez -- yukaridaki guard ile ayni istisna.
    if (
        APP_ENV in {'production', 'staging'}
        and PREFERRED_URL_SCHEME != 'https'
        and not _host_is_local_or_private(_preferred_scheme_conflict_host)
    ):
        _production_https_required_msg = (
            f"APP_ENV={APP_ENV} + cozumlenen PREFERRED_URL_SCHEME='{PREFERRED_URL_SCHEME}' "
            f"(APP_BASE_URL='{APP_BASE_URL}', host='{_preferred_scheme_conflict_host}'). "
            "Production/staging ortaminda dis sema HER ZAMAN HTTPS olmak "
            "zorundadir; acik bir PREFERRED_URL_SCHEME/APP_BASE_URL celiskisi "
            "olmasa bile sema http'de kalirsa HSTS, cookie Secure ve diger "
            "HTTPS-bagimli guvenlik sinyalleri sessizce devre disi kalir."
        )
        logger.warning(_production_https_required_msg)
        raise RuntimeError(
            "Production/staging ortaminda PREFERRED_URL_SCHEME https olmak "
            "zorundadir: " + _production_https_required_msg + " APP_BASE_URL'i "
            "https:// ile baslatin ve/veya PREFERRED_URL_SCHEME=https ayarlayin."
        )

    # BYS360_SEC3C_A1_TRUSTED_HOSTS_V1
    # Flask 3.1'in yerlesik app.config['TRUSTED_HOSTS'] Host-header dogrulamasi
    # (bkz. _resolve_trusted_hosts() docstring'i) -- her istekte Flask'in kendi
    # create_url_adapter()'i tarafindan otomatik uygulanir, ek bir
    # route_support.py kancasi GEREKMEZ.
    #
    # Enforcement kapisi BILINCLI olarak asimetriktir:
    #   - production/staging: HER ZAMAN zorlanir (liste asla None degildir --
    #     bos/None TRUSTED_HOSTS Werkzeug'de "tum host'lara guven" anlamina
    #     gelir, bu production'da kabul edilemez).
    #   - development/testing: yalnizca operator ACIKCA bir TRUSTED_HOSTS env
    #     degeri verdiyse (opt-in) zorlanir; aksi halde Flask'in varsayilan
    #     davranisi (None = tum Host basliklarina guven, mevcut/eski davranis)
    #     KORUNUR. Bu kasitli bir geriye-uyumluluk karari: repo'da zaten
    #     APP_ENV=testing altinda gercek create_app() ile kurulan, kasitli
    #     olarak SAHTE bir Host basligi gonderip uygulama mantiginin
    #     request.host'a guvenmedigini kanitlayan mevcut testler var (bkz.
    #     tests/security/test_account_change_photo_redirect_guard.py --
    #     ozellikle test_account_change_photo_direct_call_ignores_forged_
    #     host_header/..._still_honors_relative_next_under_forged_host,
    #     Host: evil.attacker.example ile test_request_context kullaniyor).
    #     Bu dosya bu gorevin izin verilen dosya listesinde DEGIL. TRUSTED_HOSTS'u
    #     testing'de kosulsuz zorlamak, Werkzeug'un request.host cached_property'
    #     sinin ilk erisimde SecurityError firlatmasina (dogrulanmis: gercek
    #     Flask app + test_request_context + TRUSTED_HOSTS=['127.0.0.1',
    #     'localhost','::1'] ile deneysel olarak dogrulandi) ve bu tamamen
    #     ilgisiz, zaten gecen testleri kirmasina yol acardi. Production/
    #     staging bu riski tasimaz (o dosya yalnizca APP_ENV=testing ile
    #     calisir) ve BYS360'in "production'da her zaman kisitla" sozlesmesi
    #     bu istisnadan bagimsiz olarak tam korunur.
    _trusted_hosts_raw_env = os.getenv('TRUSTED_HOSTS')
    _trusted_hosts_resolved = _resolve_trusted_hosts(_trusted_hosts_raw_env, APP_BASE_URL, APP_ENV)
    _trusted_hosts_explicit_opt_in = bool((_trusted_hosts_raw_env or '').strip())
    TRUSTED_HOSTS = (
        _trusted_hosts_resolved
        if APP_ENV in {'production', 'staging'} or _trusted_hosts_explicit_opt_in
        else None
    )

    DOTENV_PATH = str(DOTENV_PATH)
    REQUIRE_DOTENV_FILE = str_to_bool(os.getenv('REQUIRE_DOTENV_FILE'), APP_ENV in {'production', 'staging'})
    STRICT_ENV_VALIDATION = str_to_bool(os.getenv('STRICT_ENV_VALIDATION'), APP_ENV in {'production', 'staging'})

    # BYS360_MAINTENANCE_10_SHORT_TERM_SECRET_KEY_HARDENING
    # Production/staging ortamı güçlü SECRET_KEY olmadan başlamamalıdır.
    # Development ortamında sabit anahtar yerine her süreçte geçici anahtar üretilir.
    _raw_secret_key = (os.getenv("SECRET_KEY") or "").strip()
    _secret_placeholder_values = {
        '',
        'CHANGE_ME',
        'change-me',
        'changeme',
        'bys360-dev-session-key-change-me-before-production',
    }
    _secret_is_strong = bool(_raw_secret_key and _raw_secret_key not in _secret_placeholder_values and len(_raw_secret_key) >= 32)
    if _secret_is_strong:
        SECRET_KEY = _raw_secret_key
    elif APP_ENV in {'production', 'staging'}:
        raise RuntimeError('Production/staging ortamında güçlü ve benzersiz SECRET_KEY zorunludur.')
    else:
        SECRET_KEY = os.environ.get("FLASK_SECRET") or "bys360-local-dev-only-secret"


    _raw_database_url = (os.getenv("DATABASE_URL") or "").strip() or 'sqlite:///:memory:'
    SQLALCHEMY_DATABASE_URI = _append_db_sslmode(_raw_database_url, APP_ENV)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    _is_prod_like = APP_ENV in {'production', 'staging'}
    _default_pool_size = 25 if _is_prod_like else 10
    _default_max_overflow = 15 if _is_prod_like else 20
    _default_pool_recycle = 1800 if _is_prod_like else 900
    _default_pool_timeout = 30

    if _is_sqlite_url(SQLALCHEMY_DATABASE_URI):
        SQLALCHEMY_ENGINE_OPTIONS = {}
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_pre_ping': str_to_bool(os.getenv('DB_POOL_PRE_PING'), True),
            'pool_recycle': _coerce_positive_int(os.getenv('DB_POOL_RECYCLE'), _default_pool_recycle),
            'pool_size': _coerce_positive_int(os.getenv('DB_POOL_SIZE'), _default_pool_size),
            'max_overflow': _coerce_positive_int(os.getenv('DB_MAX_OVERFLOW'), _default_max_overflow),
            'pool_timeout': _coerce_positive_int(os.getenv('DB_POOL_TIMEOUT'), _default_pool_timeout),
            'pool_use_lifo': str_to_bool(os.getenv('DB_POOL_USE_LIFO'), True),
        }

    # BYS360_MAINTENANCE_ROADMAP_PHASE4_SCALABILITY_PERFORMANCE_CONFIG
    # Faz 4: cache, DB pool ve bildirim polling yükünü azaltma ayarları.
    CACHE_DEFAULT_TTL = _coerce_positive_int(os.getenv('CACHE_DEFAULT_TTL'), 30)
    _raw_runtime_redis_url, RUNTIME_REDIS_CONFIG_WARNING = _normalize_runtime_redis_url(os.getenv('REDIS_URL', ''), APP_ENV)
    _raw_cache_redis_url, CACHE_REDIS_CONFIG_WARNING = _normalize_runtime_redis_url(os.getenv('CACHE_REDIS_URL', _raw_runtime_redis_url), APP_ENV)
    RUNTIME_CACHE_BACKEND = os.getenv('RUNTIME_CACHE_BACKEND', 'redis' if _raw_runtime_redis_url else 'memory').strip().lower() or 'memory'
    CACHE_REDIS_URL = _raw_cache_redis_url
    NOTIFICATION_UNREAD_CACHE_TTL = _coerce_positive_int(os.getenv('NOTIFICATION_UNREAD_CACHE_TTL'), 30)
    PERFORMANCE_REPORT_CACHE_TTL = _coerce_positive_int(os.getenv('PERFORMANCE_REPORT_CACHE_TTL'), 60)
    DASHBOARD_CACHE_TTL = _coerce_positive_int(os.getenv('DASHBOARD_CACHE_TTL'), 30)

    PUBLICATION_UPLOAD_MAX_CONTENT_LENGTH = int(os.getenv('PUBLICATION_UPLOAD_MAX_CONTENT_LENGTH', 150 * 1024 * 1024))
    EDUCATION_EBOOK_MAX_CONTENT_LENGTH = int(os.getenv('EDUCATION_EBOOK_MAX_CONTENT_LENGTH', 150 * 1024 * 1024))
    _base_max_content_length = int(os.getenv('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
    MAX_CONTENT_LENGTH = max(_base_max_content_length, PUBLICATION_UPLOAD_MAX_CONTENT_LENGTH, EDUCATION_EBOOK_MAX_CONTENT_LENGTH)

    # BYS360_MAINTENANCE_ROADMAP_PHASE2_SECURITY_HARDENING_V1
    ALLOWED_UPLOAD_EXTENSIONS = os.getenv('ALLOWED_UPLOAD_EXTENSIONS', 'pdf,png,jpg,jpeg,gif,webp,docx,xlsx,pptx,zip,csv,txt').strip() or 'pdf,png,jpg,jpeg,gif,webp,docx,xlsx,pptx,zip,csv,txt'
    UPLOAD_MAX_FILENAME_LENGTH = _coerce_positive_int(os.getenv('UPLOAD_MAX_FILENAME_LENGTH'), 180)
    UPLOAD_STRICT_MIME_VALIDATION = str_to_bool(os.getenv('UPLOAD_STRICT_MIME_VALIDATION'), True)

    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'app', 'static', 'uploads'))
    # B2-F06: kişisel/kurumsal yüklemeler static klasörü dışında saklanır ve yalnız yetkili route'larla sunulur.
    PRIVATE_UPLOAD_FOLDER = os.getenv('PRIVATE_UPLOAD_FOLDER', os.path.join(BASE_DIR, 'instance', 'private_uploads'))
    REPORT_FOLDER = os.getenv('REPORT_FOLDER', os.path.join(BASE_DIR, 'reports'))
    LOG_FOLDER = os.getenv('LOG_FOLDER', os.path.join(BASE_DIR, 'logs'))
    PDF_EXPORT_MAX_ROWS_INLINE = _coerce_positive_int(os.getenv('PDF_EXPORT_MAX_ROWS_INLINE'), 250)

    SESSION_COOKIE_HTTPONLY = str_to_bool(os.getenv('SESSION_COOKIE_HTTPONLY'), True)
    SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
    SESSION_COOKIE_SECURE = _resolve_secure_cookie(
        os.getenv('SESSION_COOKIE_SECURE'), APP_ENV, APP_BASE_URL, PREFERRED_URL_SCHEME,
        cookie_name='SESSION_COOKIE_SECURE',
    )

    REMEMBER_COOKIE_HTTPONLY = str_to_bool(os.getenv('REMEMBER_COOKIE_HTTPONLY'), True)
    REMEMBER_COOKIE_SECURE = _resolve_secure_cookie(
        os.getenv('REMEMBER_COOKIE_SECURE'), APP_ENV, APP_BASE_URL, PREFERRED_URL_SCHEME,
        cookie_name='REMEMBER_COOKIE_SECURE',
    )

    WTF_CSRF_TIME_LIMIT = int(os.getenv('WTF_CSRF_TIME_LIMIT', 3600))
    SESSION_REFRESH_EACH_REQUEST = str_to_bool(os.getenv('SESSION_REFRESH_EACH_REQUEST'), True)
    PERMANENT_SESSION_LIFETIME_MINUTES = int(os.getenv('PERMANENT_SESSION_LIFETIME_MINUTES', 30))

    DEFAULT_FIRST_LOGIN_PASSWORD = os.getenv('DEFAULT_FIRST_LOGIN_PASSWORD', '').strip()

    REQUEST_GUARD_ENABLED = str_to_bool(os.getenv('REQUEST_GUARD_ENABLED'), True)
    ROOT_POST_BURST_LIMIT = _coerce_positive_int(os.getenv('ROOT_POST_BURST_LIMIT'), 8)
    ROOT_POST_WINDOW_SECONDS = _coerce_positive_int(os.getenv('ROOT_POST_WINDOW_SECONDS'), 60)
    SUSPICIOUS_PROBE_BURST_LIMIT = _coerce_positive_int(os.getenv('SUSPICIOUS_PROBE_BURST_LIMIT'), 20)
    SUSPICIOUS_PROBE_WINDOW_SECONDS = _coerce_positive_int(os.getenv('SUSPICIOUS_PROBE_WINDOW_SECONDS'), 120)
    SECURITY_LOG_COOLDOWN_SECONDS = _coerce_positive_int(os.getenv('SECURITY_LOG_COOLDOWN_SECONDS'), 300)
    REDIS_URL, REDIS_CONFIG_WARNING = _normalize_runtime_redis_url(os.getenv('REDIS_URL', ''), APP_ENV)
    CACHE_REDIS_URL, CACHE_REDIS_CONFIG_WARNING = _normalize_runtime_redis_url(os.getenv('CACHE_REDIS_URL', REDIS_URL), APP_ENV)
    CACHE_BACKEND = os.getenv('CACHE_BACKEND', 'redis' if CACHE_REDIS_URL else 'file').strip().lower() or ('redis' if CACHE_REDIS_URL else 'file')
    CACHE_KEY_PREFIX = os.getenv('CACHE_KEY_PREFIX', 'bys360').strip() or 'bys360'
    CACHE_FILE = os.getenv('CACHE_FILE', '').strip()
    REDIS_CONNECT_TIMEOUT = _coerce_float(os.getenv('REDIS_CONNECT_TIMEOUT'), 1.0)
    REDIS_SOCKET_TIMEOUT = _coerce_float(os.getenv('REDIS_SOCKET_TIMEOUT'), 1.0)

    SECURITY_RATE_LIMIT_BACKEND = os.getenv('SECURITY_RATE_LIMIT_BACKEND', 'redis' if REDIS_URL else 'file').strip().lower() or ('redis' if REDIS_URL else 'file')
    SECURITY_RATE_LIMIT_SHARED = str_to_bool(os.getenv('SECURITY_RATE_LIMIT_SHARED'), True)
    SECURITY_RATE_LIMIT_FILE = os.getenv('SECURITY_RATE_LIMIT_FILE', '').strip()
    SECURITY_RATE_LIMIT_REDIS_URL, SECURITY_RATE_LIMIT_REDIS_CONFIG_WARNING = _normalize_runtime_redis_url(os.getenv('SECURITY_RATE_LIMIT_REDIS_URL', REDIS_URL), APP_ENV)

    LOGIN_THROTTLE_ENABLED = str_to_bool(os.getenv('LOGIN_THROTTLE_ENABLED'), True)
    LOGIN_IP_MAX_ATTEMPTS = _coerce_positive_int(os.getenv('LOGIN_IP_MAX_ATTEMPTS'), 12)
    LOGIN_IDENTITY_MAX_ATTEMPTS = _coerce_positive_int(os.getenv('LOGIN_IDENTITY_MAX_ATTEMPTS'), 6)
    LOGIN_LOCKOUT_MINUTES = _coerce_positive_int(os.getenv('LOGIN_LOCKOUT_MINUTES'), 15)

    FEEDBACK_PULSE_ANALYTICS_CACHE_ENABLED = str_to_bool(os.getenv('FEEDBACK_PULSE_ANALYTICS_CACHE_ENABLED'), True)
    FEEDBACK_PULSE_ANALYTICS_CACHE_TTL_SECONDS = _coerce_positive_int(os.getenv('FEEDBACK_PULSE_ANALYTICS_CACHE_TTL_SECONDS'), 60)

    LOGIN_CAPTCHA_THRESHOLD = int(os.getenv('LOGIN_CAPTCHA_THRESHOLD', 3))
    LOGIN_FAILURE_WINDOW_MINUTES = int(os.getenv('LOGIN_FAILURE_WINDOW_MINUTES', 30))
    LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER = str_to_bool(os.getenv('LOGIN_FORCE_CAPTCHA_FOR_UNKNOWN_USER'), True)
    LOGIN_GENERIC_ERROR_MESSAGE = (
        os.getenv('LOGIN_GENERIC_ERROR_MESSAGE', 'Giriş başarısız. Bilgilerinizi kontrol edip tekrar deneyin.').strip()
        or 'Giriş başarısız. Bilgilerinizi kontrol edip tekrar deneyin.'
    )

    AUTO_REPAIR_SCHEMA = str_to_bool(os.getenv('AUTO_REPAIR_SCHEMA'), False)
    STRICT_SCHEMA_CHECK = str_to_bool(os.getenv('STRICT_SCHEMA_CHECK'), APP_ENV in {'production', 'staging'})

    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').strip().upper() or 'INFO'
    APP_LOG_FILE_MAX_BYTES = _coerce_positive_int(os.getenv('APP_LOG_FILE_MAX_BYTES'), 2_000_000)
    APP_LOG_BACKUP_COUNT = _coerce_positive_int(os.getenv('APP_LOG_BACKUP_COUNT'), 5)
    OPS_LOG_FILE_MAX_BYTES = _coerce_positive_int(os.getenv('OPS_LOG_FILE_MAX_BYTES'), 2_000_000)
    OPS_LOG_BACKUP_COUNT = _coerce_positive_int(os.getenv('OPS_LOG_BACKUP_COUNT'), 5)

    PROXY_FIX_ENABLED = str_to_bool(os.getenv('PROXY_FIX_ENABLED'), APP_ENV in {'production', 'staging'})
    PROXY_FIX_X_FOR = _coerce_positive_int(os.getenv('PROXY_FIX_X_FOR'), 1)
    PROXY_FIX_X_PROTO = _coerce_positive_int(os.getenv('PROXY_FIX_X_PROTO'), 1)
    PROXY_FIX_X_HOST = _coerce_positive_int(os.getenv('PROXY_FIX_X_HOST'), 1)
    PROXY_FIX_X_PORT = _coerce_positive_int(os.getenv('PROXY_FIX_X_PORT'), 1)
    PROXY_FIX_X_PREFIX = _coerce_positive_int(os.getenv('PROXY_FIX_X_PREFIX'), 1)

    WAITRESS_THREADS = _coerce_positive_int(os.getenv('WAITRESS_THREADS'), 12 if _is_prod_like else 4)
    GUNICORN_BIND = os.getenv('GUNICORN_BIND', f"{os.getenv('APP_HOST', '0.0.0.0')}:{os.getenv('APP_PORT', '8000')}").strip() or '0.0.0.0:8000'
    GUNICORN_WORKERS = _coerce_positive_int(os.getenv('GUNICORN_WORKERS'), 3)
    GUNICORN_WORKER_CLASS = os.getenv('GUNICORN_WORKER_CLASS', 'gevent').strip() or 'gevent'
    GUNICORN_TIMEOUT = _coerce_positive_int(os.getenv('GUNICORN_TIMEOUT'), 120)
    GUNICORN_KEEPALIVE = _coerce_positive_int(os.getenv('GUNICORN_KEEPALIVE'), 5)
    GUNICORN_LOG_LEVEL = os.getenv('GUNICORN_LOG_LEVEL', LOG_LEVEL).strip().lower() or 'info'

    TCKN_ENCRYPTION_KEY = os.getenv('TCKN_ENCRYPTION_KEY', '').strip()

    # BYS360_MAINTENANCE_ROADMAP_PHASE2_SECURITY_HARDENING_V1
    SENTRY_DSN = (os.getenv("SENTRY_DSN") or "").strip()
    SENTRY_ENVIRONMENT = os.getenv('SENTRY_ENVIRONMENT', APP_ENV).strip() or APP_ENV
    SENTRY_RELEASE = os.getenv('SENTRY_RELEASE', '').strip()
    SENTRY_TRACES_SAMPLE_RATE = _coerce_float(os.getenv('SENTRY_TRACES_SAMPLE_RATE'), 0.1)
    SENTRY_PROFILES_SAMPLE_RATE = _coerce_float(os.getenv('SENTRY_PROFILES_SAMPLE_RATE'), 0.0)
    SENTRY_SEND_DEFAULT_PII = str_to_bool(os.getenv('SENTRY_SEND_DEFAULT_PII'), False)
    SENTRY_REQUIRED_IN_PRODUCTION = str_to_bool(os.getenv('SENTRY_REQUIRED_IN_PRODUCTION'), False)

    MAINTENANCE_MODE = str_to_bool(os.getenv('MAINTENANCE_MODE'), False)
    MAINTENANCE_MESSAGE = os.getenv('MAINTENANCE_MESSAGE', 'Sistem şu anda planlı bakım modunda. Lütfen kısa süre sonra tekrar deneyin.').strip()
    SLOW_REQUEST_THRESHOLD_MS = int(os.getenv('SLOW_REQUEST_THRESHOLD_MS', 1000))

    CSP_ENABLED = str_to_bool(os.getenv('CSP_ENABLED'), True)
    # BYS360_MAINTENANCE_10_SHORT_TERM_CSP_ENFORCE_DEFAULT
    # Geliştirmede raporlama, production/staging ortamında aksi belirtilmezse enforce.
    CSP_REPORT_ONLY = str_to_bool(os.getenv('CSP_REPORT_ONLY'), APP_ENV not in {'production', 'staging'})
    CSP_POLICY = os.getenv('CSP_POLICY', '').strip()
    CSP_NONCE_ENABLED = str_to_bool(os.getenv('CSP_NONCE_ENABLED'), APP_ENV in {'production', 'staging'})
    CSP_ALLOW_UNSAFE_INLINE_SCRIPT = str_to_bool(os.getenv('CSP_ALLOW_UNSAFE_INLINE_SCRIPT'), False)
    CSP_DEFAULT_SRC = os.getenv('CSP_DEFAULT_SRC', "'self'").strip() or "'self'"
    CSP_BASE_URI = os.getenv('CSP_BASE_URI', "'self'").strip() or "'self'"
    CSP_FORM_ACTION = os.getenv('CSP_FORM_ACTION', "'self'").strip() or "'self'"
    CSP_FRAME_ANCESTORS = os.getenv('CSP_FRAME_ANCESTORS', "'self'").strip() or "'self'"
    CSP_IMG_SRC = os.getenv('CSP_IMG_SRC', "'self' data: blob: https:").strip() or "'self' data: blob: https:"
    CSP_STYLE_SRC = os.getenv('CSP_STYLE_SRC', "'self' 'unsafe-inline' https:").strip() or "'self' 'unsafe-inline' https:"
    CSP_STYLE_SRC_ELEM = os.getenv('CSP_STYLE_SRC_ELEM', "'self' 'unsafe-inline' https:").strip() or "'self' 'unsafe-inline' https:"
    CSP_STYLE_SRC_ATTR = os.getenv('CSP_STYLE_SRC_ATTR', "'unsafe-inline'").strip() or "'unsafe-inline'"
    # BYS360_P0_SECURITY_OBSERVABILITY_V1: script tarafinda unsafe-inline varsayilan kapali; nonce uygulanir.
    CSP_SCRIPT_SRC = os.getenv('CSP_SCRIPT_SRC', "'self' https:").strip() or "'self' https:"
    CSP_FONT_SRC = os.getenv('CSP_FONT_SRC', "'self' data: https:").strip() or "'self' data: https:"
    CSP_CONNECT_SRC = os.getenv('CSP_CONNECT_SRC', "'self' https:").strip() or "'self' https:"
    CSP_OBJECT_SRC = os.getenv('CSP_OBJECT_SRC', "'none'").strip() or "'none'"
    HSTS_POLICY = os.getenv('HSTS_POLICY', 'max-age=31536000; includeSubDomains').strip() or 'max-age=31536000; includeSubDomains'
    REFERRER_POLICY = os.getenv('REFERRER_POLICY', 'strict-origin-when-cross-origin').strip() or 'strict-origin-when-cross-origin'
    PERMISSIONS_POLICY = os.getenv('PERMISSIONS_POLICY', 'geolocation=(), microphone=(), camera=()').strip() or 'geolocation=(), microphone=(), camera=()'
    CACHE_CONTROL_POLICY = os.getenv('CACHE_CONTROL_POLICY', 'no-store').strip() or 'no-store'
    CROSS_ORIGIN_OPENER_POLICY = os.getenv('CROSS_ORIGIN_OPENER_POLICY', 'same-origin').strip() or 'same-origin'
    CROSS_ORIGIN_RESOURCE_POLICY = os.getenv('CROSS_ORIGIN_RESOURCE_POLICY', 'same-origin').strip() or 'same-origin'
    TCKN_ALLOWED_ROLES = tuple(item.strip() for item in os.getenv('TCKN_ALLOWED_ROLES', 'admin,baskan,baskan_yardimcisi,grup_baskani,koordinator').split(',') if item.strip())

    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.office365.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
    ALLOWED_EMAIL_DOMAINS = tuple(item.strip().lower() for item in os.getenv('ALLOWED_EMAIL_DOMAINS', 'ktb.gov.tr').split(',') if item.strip()) or ('ktb.gov.tr',)
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', '')

    AI_ENABLED = str_to_bool(os.getenv('AI_ENABLED'), True)
    AI_PROVIDER_MODE = os.getenv('AI_PROVIDER_MODE', 'stub').strip().lower() or 'stub'
    AI_PROVIDER_NAME = os.getenv('AI_PROVIDER_NAME', 'internal_stub_plus').strip() or 'internal_stub_plus'
    AI_MODEL_NAME = os.getenv('AI_MODEL_NAME', 'bys360-ai-stub-v2').strip() or 'bys360-ai-stub-v2'
    AI_BASE_URL = os.getenv('AI_BASE_URL', '').strip().rstrip('/')
    AI_API_KEY = os.getenv('AI_API_KEY', '').strip()
    AI_REQUEST_PATH = os.getenv('AI_REQUEST_PATH', '/chat/completions').strip() or '/chat/completions'
