"""CSP strict migration - Wave 1 contract.

BYS360 `app/security/headers.py` uygular:
    script-src: 'self' https:  (unsafe-inline YOK)

Bu nedenle inline event-attribute'lar (onclick=, onerror= vb.) ve
`javascript:` URL'ler enforce modunda (CSP_REPORT_ONLY kapali) tarayici
tarafindan calistirilmaz. Bu test, Wave 1 kapsamindaki template'lerde
(hata sayfalari, login/forgot-password/account-security akisi ve paylasilan
base.html iskeleti) bu iki desenin artik bulunmadigini ve kaldirilan
davranisin yerine data-* attribute + addEventListener tabanli bir
mekanizmanin konuldugunu dogrular.

Bu bir static/kaynak-kod kontrat testidir; gercek bir tarayicida CSP
enforce edilmis haliyle calisma zamani davranisini DOGRULAMAZ.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.fixture
def client(app):
    """Fresh anonymous client. These contracts render public pages (/login,
    /forgot-password, /offline); the session-scoped shared client may still be
    logged in by an earlier module, and /login then redirects (302)."""
    return app.test_client()


REPO_ROOT = Path(__file__).resolve().parents[2]

# Wave 1 sahiplik alani: hata sayfalari + login/auth akisi + paylasilan base.html
WAVE1_TEMPLATES = [
    "app/templates/errors/400.html",
    "app/templates/errors/401.html",
    "app/templates/errors/403.html",
    "app/templates/errors/404.html",
    "app/templates/errors/405.html",
    "app/templates/errors/413.html",
    "app/templates/errors/500.html",
    "app/templates/errors/503.html",
    "app/templates/login.html",
    "app/templates/forgot_password.html",
    "app/templates/account_security_setup.html",
    "app/templates/account_change_password.html",
    "app/templates/base.html",
]

# HTML attribute syntax: bosluk + on<harfler> + '=' + tirnak. CSS/JS icindeki
# "javascript:" gibi metinsel string literal'leri yanlislikla yakalamaz.
_INLINE_EVENT_ATTR_RE = re.compile(r"""[\s]on[a-zA-Z]+\s*=\s*["']""")
_JS_HREF_RE = re.compile(r"""href\s*=\s*["']\s*javascript:""", re.IGNORECASE)


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


@pytest.mark.parametrize("relative_path", WAVE1_TEMPLATES)
def test_wave1_template_has_no_inline_event_attributes(relative_path: str) -> None:
    text = _read(relative_path)
    matches = _INLINE_EVENT_ATTR_RE.findall(text)
    assert not matches, (
        f"{relative_path} icinde inline event-attribute (on*=) bulundu: {matches!r}. "
        "CSP script-src 'self' https: (unsafe-inline yok) altinda bunlar calismaz; "
        "data-* attribute + addEventListener kalibina cevrilmeli."
    )


@pytest.mark.parametrize("relative_path", WAVE1_TEMPLATES)
def test_wave1_template_has_no_javascript_href(relative_path: str) -> None:
    text = _read(relative_path)
    matches = _JS_HREF_RE.findall(text)
    assert not matches, (
        f"{relative_path} icinde href=\"javascript:...\" bulundu: {matches!r}. "
        "CSP script-src bunu da kapsar; gercek <a>/<button> + addEventListener "
        "kalibina cevrilmeli."
    )


@pytest.mark.parametrize("relative_path", WAVE1_TEMPLATES)
def test_wave1_template_introduces_no_dangerous_js_sinks(relative_path: str) -> None:
    """Duzeltme sirasinda eval/new Function/document.write eklenmedigini dogrular."""
    text = _read(relative_path)
    for forbidden in ("eval(", "new Function(", "document.write("):
        assert forbidden not in text, f"{relative_path} icinde yasakli sink bulundu: {forbidden}"


def test_error_pages_use_data_action_history_back_instead_of_js_url() -> None:
    for relative_path in ("app/templates/errors/403.html", "app/templates/errors/413.html"):
        text = _read(relative_path)
        assert 'data-action="history-back"' in text
        assert "history.back()" in text  # artik JS icinde addEventListener uzerinden cagriliyor
        assert "querySelectorAll('[data-action=\"history-back\"]')" in text
        assert "addEventListener('click'" in text


def test_login_and_forgot_password_use_data_fallback_src_for_logo() -> None:
    for relative_path in ("app/templates/login.html", "app/templates/forgot_password.html"):
        text = _read(relative_path)
        assert "data-fallback-src=" in text
        assert "onerror=" not in text
        assert "img[data-fallback-src]" in text
        assert "addEventListener('error'" in text


def test_base_html_logout_links_use_data_attribute_not_inline_onclick() -> None:
    text = _read("app/templates/base.html")
    assert 'onclick="return submitLogoutForm(event);"' not in text
    assert text.count('data-logout-trigger="true"') == 2
    assert "querySelectorAll('[data-logout-trigger]')" in text
    assert "addEventListener('click', submitLogoutForm)" in text


def test_base_html_avatar_and_brand_logos_use_data_fallback_src() -> None:
    text = _read("app/templates/base.html")
    assert "onerror=" not in text
    assert text.count("data-fallback-src=") >= 5
    assert "img[data-fallback-src]" in text


def test_base_html_javascript_string_filter_is_not_a_javascript_url() -> None:
    """base.html icindeki `.startsWith('javascript:')` kontrolleri, dinamik
    nav linklerini FILTRELEMEK icin JS string karsilastirmasidir; bir
    href="javascript:..." URL'i DEGILDIR. Bu test, gercek bir javascript:
    href regresyonu olmadigini href-spesifik regex ile ayrica dogrular
    (genel 'javascript:' metin arama testinden kasitli olarak farklidir)."""
    text = _read("app/templates/base.html")
    assert "javascript:" in text  # filtre mantigi icin beklenen, zararsiz
    assert not _JS_HREF_RE.search(text)


# ---------------------------------------------------------------------------
# Calisma-zamani render kontrolleri (Flask test client uzerinden gercek HTTP
# GET + Jinja render). Bu HALA bir gercek tarayici testi DEGILDIR: CSP
# enforce edilmis bir tarayicida script'lerin fiilen calistigini kanitlamaz,
# sadece uretilen HTML'de inline event-attribute/javascript: href kalmadigini
# ve data-* kancalarinin gercekten render edildigini dogrular.
# ---------------------------------------------------------------------------


def test_login_page_render_has_no_inline_handlers(client) -> None:
    response = client.get("/login")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    assert not _JS_HREF_RE.search(html)
    assert "data-fallback-src=" in html


def test_forgot_password_page_render_has_no_inline_handlers(client) -> None:
    response = client.get("/forgot-password")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    assert not _JS_HREF_RE.search(html)


def test_error_403_page_render_has_no_inline_handlers(app) -> None:
    with app.test_request_context("/"):
        from flask import render_template

        html = render_template("errors/403.html")
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    assert not _JS_HREF_RE.search(html)
    assert 'data-action="history-back"' in html


def test_error_413_page_render_has_no_inline_handlers(app) -> None:
    with app.test_request_context("/"):
        from flask import render_template

        html = render_template("errors/413.html")
    assert not _INLINE_EVENT_ATTR_RE.findall(html)
    assert not _JS_HREF_RE.search(html)
    assert 'data-action="history-back"' in html
