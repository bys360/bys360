"""BYS360 UX dalga 4 -- Yardım Merkezi (support/index.html) sözleşme testleri.

Şablon /support rotasında kullanılır. Bu dalgada yalnız sunum değişti: rota,
bağlam verisi (app/support/help_center_content.py), bağlantı hedefleri ve sayaç
kuralları aynı kaldı. 13 statik style="..." özniteliği sınıflara taşındı
(STYLE_MIGRATION_WAVES["ux_wave4_help_center"]).

Rehber içerik metinleri (başlık, özet) bu dalgada değiştirilmedi; içlerindeki
İngilizce terimler (ör. "AI", "Dashboard") ayrı bir içerik/terim kararına
bırakıldı. Türkçe testi bu yüzden şablonun KENDİ yazdığı metni denetler ve
bulunan her İngilizce ifadenin içerik verisinden geldiğini kanıtlar.

Testler sahte kullanıcı ve sahte veriyle, her test için ayrı geçici SQLite
veritabanında çalışır (pilot test dosyasıyla aynı yardımcılar).
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
    _valid_form,
    _VisibleUiText,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_TEMPLATE = REPO_ROOT / "app/templates/support/index.html"


@pytest.fixture
def app(monkeypatch):
    return _make_app(monkeypatch)


@pytest.fixture
def client(app):
    return app.test_client()


def _help_html(client) -> str:
    response = client.get("/support")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _content_strings(app) -> set[str]:
    """Yardım merkezi bağlam verisindeki bütün metinler (rehber içerikleri)."""
    from app.support.help_center_content import build_home_context

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
        walk(build_home_context())
    return found


# ---------------------------------------------------------------------------
# Statik: CSP ve tasarım sistemi
# ---------------------------------------------------------------------------
def test_help_center_template_has_no_inline_style_block_script_or_handler() -> None:
    text = INDEX_TEMPLATE.read_text(encoding="utf-8")
    assert "<style" not in text.lower()
    assert not re.search(r"\sstyle\s*=", text), "Statik style özniteliği kaldı"
    assert not re.search(r"\son[a-z]+\s*=", text, re.IGNORECASE)
    assert "|safe" not in text
    scripts = re.findall(r"<script\b[^>]*>", text)
    assert scripts and all("src=" in tag for tag in scripts)
    for asset in ("css/bys360_support_learning.css", "css/bys360_tokens.css", "css/bys360_components.css",
                  "js/bys360_support_learning.js"):
        assert asset in text, asset
    assert "bys360_ui_form.js" not in text, "Yardım merkezinde form yok; form betiği yüklenmemeli"


# ---------------------------------------------------------------------------
# İçerik ve bağlantılar korunuyor
# ---------------------------------------------------------------------------
def test_all_content_groups_and_links_are_still_rendered(app, client) -> None:
    from app.support.help_center_content import build_home_context

    _logged_in(app, client, sicil_no="90951", role="personel")
    html = _help_html(client)
    with app.test_request_context():
        context = build_home_context()

    for article in context["featured_articles"] + context["troubleshooting_articles"]:
        assert f'href="/support/help/article/{article["slug"]}"' in html, article["slug"]
    for group in context["module_groups"]:
        assert f'href="/support/help/category/{group["slug"]}"' in html, group["slug"]
        if group.get("learning_goal"):
            assert "Öğrenme hedefi:" in html
        for article in group["articles"]:
            assert f'href="/support/help/article/{article["slug"]}"' in html
    for path in context["learning_paths"]:
        for article in path["steps"]:
            assert f'href="/support/help/article/{article["slug"]}"' in html
    for step in context["support_process_steps"]:
        assert step["title"] in html and step["text"] in html
    for item in context["support_status_flow"] + context["support_intake_examples"] + context["help_quality_cards"]:
        assert item.get("text", "") in html
    for query in context["suggested_queries"]:
        assert query in html
    for slug in ("destek-talebi-nasil-acilir", "talep-durumlari-nasil-takip-edilir"):
        assert f'href="/support/help/article/{slug}"' in html


def test_search_form_is_labelled_and_targets_help_search(app, client) -> None:
    _logged_in(app, client, sicil_no="90952", role="personel")
    html = _help_html(client)
    form = re.search(r'<form [^>]*action="/support/help/search"[^>]*>.*?</form>', html, re.DOTALL)
    assert form and 'method="get"' in form.group(0) and 'role="search"' in form.group(0)
    assert '<label class="bys-field__label" for="help-search">Aranacak konu</label>' in form.group(0)
    assert re.search(r'<input [^>]*type="search" id="help-search" name="q"', form.group(0))
    assert client.get("/support/help/search?q=talep").status_code == 200


def test_ticket_counters_reflect_own_tickets_and_keep_their_links(app, client) -> None:
    _logged_in(app, client, sicil_no="90953", role="personel")
    for title in ("Sahte talep: birinci", "Sahte talep: ikinci"):
        assert client.post("/support/new", data=_valid_form(title=title)).status_code == 302
    html = _help_html(client)
    stats = re.search(r'<ul class="bys-stats bys-stats--links[^"]*">(.*?)</ul>', html, re.DOTALL)
    assert stats
    items = re.findall(r'<a class="bys-stat bys-stat--link" href="([^"]+)"><span class="bys-stat__value">(\d+)</span><span class="bys-stat__label">([^<]+)</span>', stats.group(1))
    assert [(label, value) for _href, value, label in items] == [
        ("Açık talebim", "2"), ("Toplam talebim", "2"), ("Bana atanan", "0"), ("Çözülen kayıt", "0"),
    ]
    hrefs = [href for href, _value, _label in items]
    # Personel için "Bana atanan" eskisi gibi Taleplerim'e gider.
    assert hrefs[:3] == ["/support/my-tickets"] * 3
    assert hrefs[3].startswith("/support/help/search?q=")


def test_other_users_tickets_do_not_change_my_counters(app, client) -> None:
    other = app.test_client()
    _logged_in(app, other, sicil_no="90954", role="personel")
    assert other.post("/support/new", data=_valid_form(title="Sahte başkasının talebi")).status_code == 302
    _logged_in(app, client, sicil_no="90955", role="personel")
    html = _help_html(client)
    assert re.findall(r'<span class="bys-stat__value">(\d+)</span>', html)[:2] == ["0", "0"]
    assert "Sahte başkasının talebi" not in html


def test_help_admin_link_is_only_for_help_content_managers(app, client) -> None:
    _logged_in(app, client, sicil_no="90956", role="personel")
    assert 'href="/support/help-admin"' not in _help_html(client)


def test_process_steps_do_not_repeat_their_own_numbers() -> None:
    text = INDEX_TEMPLATE.read_text(encoding="utf-8")
    process = text[text.index("support_process_steps"):]
    process = process[: process.index("</ul>")]
    assert '<ul class="bys-steps bys-steps--icons">' in text
    assert "loop.index" not in process


# ---------------------------------------------------------------------------
# Türkçe arayüz standardı
# ---------------------------------------------------------------------------
def test_tr_template_text_is_turkish_and_english_only_comes_from_help_content(app, client) -> None:
    _logged_in(app, client, sicil_no="90957", role="personel")
    html = _help_html(client)
    scanner = _VisibleUiText("support-learning-shell")
    scanner.feed(html)
    assert scanner.strings
    content = _content_strings(app)
    template_findings = []
    for finding in _english_ui_findings(scanner.strings):
        source = finding.split(" <- ", 1)[1].strip("'")
        if source.lstrip(": ").strip() not in content:
            template_findings.append(finding)
    assert template_findings == [], "Şablonun kendi metninde İngilizce:\n" + "\n".join(template_findings)
    for old in ("Canlı Kullanım, Rehber ve Destek Merkezi", "omurgası", "Rehber Ara"):
        assert old not in html
