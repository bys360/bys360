"""BYS360 UX dalga 5 -- rehber makale / kategori / rol / arama ekranları sözleşme testleri.

Şablonlar: support/help_article.html, help_category.html, help_role.html,
help_search.html. Bu dalgada yalnız sunum değişti: rotalar, bağlam verisi
(app/support/help_center_content.py), arama işlevi ve sorgu parametresi aynı
kaldı. 9 statik style="..." özniteliği sınıflara taşındı
(STYLE_MIGRATION_WAVES["ux_wave5_help_pages"]).

Makaledeki bağlantı kopyalama ve yazdırma düğmelerinin işaretlemesi Wave-7 CSP
sözleşmesince sabitlenmiştir (tests/security/test_csp_wave7_support_help_contract.py);
yazdırma görünümü bys360_support_learning.css'teki support-actions /
support-aside / support-print sınıflarına bağlıdır.

Rehber içerik metinleri değiştirilmedi; Türkçe testi şablonun kendi metnini
denetler ve her İngilizce bulgunun içerik verisinden geldiğini kanıtlar.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from test_pilot_support_new_ux_contract import (
    _english_ui_findings,
    _logged_in,
    _make_app,
    _VisibleUiText,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = {
    name: REPO_ROOT / f"app/templates/support/{name}.html"
    for name in ("help_article", "help_category", "help_role", "help_search")
}
SUGGESTED_QUERIES = ["destek talebi", "personel raporları", "performans dönemi", "nabız analitiği",
                     "yapay zekâ özeti", "menü yetkisi", "oturum güvenliği"]


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _get(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    return response.get_data(as_text=True)


def _content_strings(app) -> set[str]:
    """Rehber içerik verisindeki bütün metinler (makale, kategori, rol)."""
    from app.support import help_center_content as content

    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.add(value.strip())
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    with app.test_request_context():
        walk(content.get_all_articles())
        walk(content.HELP_CATEGORIES)
        walk(content.HELP_ROLES)
    return found


# ---------------------------------------------------------------------------
# Statik: CSP, tasarım sistemi, yazdırma ve Wave-7 işaretlemesi
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_help_page_has_no_inline_style_script_or_handler(name: str) -> None:
    text = TEMPLATES[name].read_text(encoding="utf-8")
    assert "<style" not in text.lower()
    assert not re.search(r"\sstyle\s*=", text), "Statik style özniteliği kaldı"
    assert not re.search(r"\son[a-z]+\s*=", text, re.IGNORECASE)
    assert "|safe" not in text
    assert "<script>" not in text
    assert text.count("<script") == 1 and "js/bys360_support_learning.js" in text
    for asset in ("css/bys360_support_learning.css", "css/bys360_tokens.css", "css/bys360_components.css"):
        assert asset in text, asset
    assert "bys-ui bys-page" in text


def test_article_keeps_print_and_copy_hooks() -> None:
    text = TEMPLATES["help_article"].read_text(encoding="utf-8")
    assert '<button class="support-btn-soft" type="button" id="helpArticlePrintBtn">' in text
    assert ('<button class="support-btn-soft" type="button" data-copy-support-link>'
            '<i class="fa-solid fa-link"></i> Bağlantıyı Kopyala</button>') in text
    for print_hook in ('class="support-actions', 'class="support-aside', 'class="support-print"', 'class="support-article-shell'):
        assert print_hook in text, print_hook
    css = (REPO_ROOT / "app/static/css/bys360_components.css").read_text(encoding="utf-8")
    print_block = css[css.index("@media print {"):]
    assert ".bys-ui .bys-article-layout" in print_block.split("}")[0] + "}" and "display: block" in print_block[:200]


# ---------------------------------------------------------------------------
# Makale
# ---------------------------------------------------------------------------
def test_article_renders_sections_toc_related_and_ticket_link(app, client) -> None:
    from app.support.help_center_content import get_article

    _logged_in(app, client, sicil_no="90961", role="personel")
    with app.test_request_context():
        article = get_article("destek-talebi-nasil-acilir")
    assert article and article["sections"]
    html = _get(client, "/support/help/article/destek-talebi-nasil-acilir")

    assert f'<h2 class="bys-prose__title" id="helpArticleTitle">{article["title"]}</h2>' in html
    for index in range(1, len(article["sections"]) + 1):
        assert f'id="section-{index}"' in html
        assert f'<a data-support-anchor href="#section-{index}">' in html
    for related in article.get("related_articles") or []:
        assert f'href="/support/help/article/{related["slug"]}"' in html
    assert 'href="/support/new"' in html
    assert html.count('id="helpArticlePrintBtn"') == 1


def test_unknown_help_pages_still_404(app, client) -> None:
    _logged_in(app, client, sicil_no="90962", role="personel")
    for path in ("/support/help/article/olmayan-rehber", "/support/help/category/olmayan", "/support/help/role/olmayan"):
        assert client.get(path).status_code == 404, path


# ---------------------------------------------------------------------------
# Kategori ve rol
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("kind", "slug"), [("category", "performans"), ("role", "personel")])
def test_category_and_role_list_every_article_with_count(app, client, kind, slug) -> None:
    from app.support.help_center_content import get_category, get_role

    _logged_in(app, client, sicil_no=f"9096{3 if kind == 'category' else 4}", role="personel")
    with app.test_request_context():
        data = get_category(slug) if kind == "category" else get_role(slug)
    assert data and data["articles"]
    html = _get(client, f"/support/help/{kind}/{slug}")
    links = re.findall(r'<a class="bys-article-link" href="/support/help/article/([^"]+)">', html)
    assert links == [article["slug"] for article in data["articles"]]
    assert f'{data["article_count"]} rehber · {data["coverage_level"]} kapsam' in html
    assert 'href="/support"' in html


# ---------------------------------------------------------------------------
# Arama
# ---------------------------------------------------------------------------
def test_search_form_is_labelled_echoes_escaped_query_and_counts(app, client) -> None:
    _logged_in(app, client, sicil_no="90965", role="personel")
    html = _get(client, "/support/help/search?q=destek+talebi")
    assert '<label class="bys-field__label" for="help-search">Aranacak konu</label>' in html
    assert re.search(r'<input [^>]*type="search" id="help-search" name="q" value="destek talebi"', html)
    count = re.search(r"için (\d+) rehber bulundu\.", html)
    assert count and int(count.group(1)) == len(re.findall(r'<a class="bys-article-link"', html)) > 0

    payload = '<img src=x onerror="alert(1)">'
    escaped = _get(client, "/support/help/search?q=" + payload)
    assert payload not in escaped and "&lt;img src=x onerror=" in escaped


@pytest.mark.parametrize("query", SUGGESTED_QUERIES)
def test_every_turkish_suggestion_finds_guides(app, client, query) -> None:
    """Öneri bağlantıları Türkçe; her biri en az bir rehber bulmalı (İngilizce "AI özet",
    "CSRF" önerilerinin yerine geçenler dahil)."""
    _logged_in(app, client, sicil_no="90966", role="personel")
    page = _get(client, "/support/help/search")
    assert f">{query}</a>" in page
    results = _get(client, "/support/help/search?q=" + query)
    assert len(re.findall(r'<a class="bys-article-link"', results)) >= 1, query


def test_search_without_result_offers_a_ticket(app, client) -> None:
    _logged_in(app, client, sicil_no="90967", role="personel")
    html = _get(client, "/support/help/search?q=bulunmayan-ifade-xyz")
    assert "Aramanıza uygun rehber bulunamadı." in html
    assert 'href="/support/new"' in html
    assert "CSRF" not in html.split("Aramanıza uygun rehber bulunamadı.")[1].split("</div>")[0]


# ---------------------------------------------------------------------------
# Türkçe arayüz standardı
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "/support/help/article/destek-talebi-nasil-acilir",
    "/support/help/article/ai-ozeti-nasil-yorumlanir",
    "/support/help/category/performans",
    "/support/help/role/personel",
    "/support/help/search",
    "/support/help/search?q=yapay+zekâ+özeti",
    "/support/help/search?q=bulunmayan-ifade",
])
def test_tr_template_text_is_turkish_and_english_only_comes_from_help_content(app, client, path) -> None:
    _logged_in(app, client, sicil_no="90968", role="personel")
    html = _get(client, path)
    scanner = _VisibleUiText("support-learning-shell")
    scanner.feed(html)
    assert scanner.strings
    content = _content_strings(app)
    template_findings = []
    for finding in _english_ui_findings(scanner.strings):
        source = finding.split(" <- ", 1)[1].strip("'").lstrip(": ").strip()
        if source not in content:
            template_findings.append(finding)
    assert template_findings == [], "Şablonun kendi metninde İngilizce:\n" + "\n".join(template_findings)
