import json
from pathlib import Path

import pytest

from sync.aac_mcp_sync import FailClosed, check_response, collect, faq_items, html_to_text, publish, refresh_faq


def _page(items, kind="posts"):
    body = json.dumps(items).encode()
    return 200, "application/json; charset=utf-8", body, f"https://aiagentcycle.com/wp-json/wp/v2/{kind}"


def _item(id, slug, link, content="<p>Kennis</p>", title="Audit", excerpt=""):
    return {"id": id, "slug": slug, "modified": "2026-10-20T00:00:00", "link": link, "title": {"rendered": title},
            "content": {"rendered": content}, "excerpt": {"rendered": excerpt}, "author": 3, "_links": {"self": []}}


def test_html_and_fail_closed():
    assert "hallo" in html_to_text("<p>hallo</p><script>alert(1)</script>")
    assert "alert" not in html_to_text("<p>hallo</p><script>alert(1)</script>")
    with pytest.raises(FailClosed):
        check_response(403, "application/json", b"[]", "https://aiagentcycle.com/x")
    with pytest.raises(FailClosed):
        check_response(200, "text/html", b"<html>challenge</html>", "https://aiagentcycle.com/x")
    with pytest.raises(FailClosed):
        check_response(200, "application/json", b"<html>challenge</html>", "https://aiagentcycle.com/x")
    with pytest.raises(FailClosed):
        check_response(200, "application/json", b"[]", "https://evil.example/x")
    leaked = check_response(200, "text/html", b'[{"id":1,"slug":"a"}]', "https://aiagentcycle.com/x", check_content_type=False)
    assert leaked[0]["id"] == 1


def test_html_keeps_cells_prices_headings_and_drops_forms():
    text = html_to_text(
        "<h2>Prijzen</h2><table><tr><td><a>Quick-win</a></td><td><strong>Vanaf €750</strong></td><td>Eén proces</td></tr></table>"
        "<p><strong>€250</strong><span>per maand, excl. btw</span></p><ul><li><b>Normale invoer</b><span>wat er moet</span></li></ul>"
        "<form><label>Naam</label><input></form><p>Na het formulier</p>"
        "<p><strong>5 uur per week</strong>aan één proces. <strong>Let op</strong>: <a>Plan</a><a>Bekijk</a></p>"
    )
    assert "5 uur per week aan één proces. Let op: Plan Bekijk" in text
    assert "## Prijzen" in text
    assert "Quick-win | Vanaf €750 | Eén proces" in text
    assert "€250 per maand, excl. btw" in text
    assert "- Normale invoer wat er moet" in text
    assert "Naam" not in text and "Na het formulier" in text


def test_collect_all_kinds_types_skips_and_writes(tmp_path: Path):
    data = {
        "posts": [_item(9, "audit", "https://aiagentcycle.com/nl/kennisbank/audit/")],
        "pages": [_item(907, "afas", "https://aiagentcycle.com/nl/koppelingen/afas/", title="AFAS"),
                  _item(894, "koppelingen", "https://aiagentcycle.com/nl/koppelingen/", title="Koppelingen"),
                  _item(875, "nieuwsbrief-bevestigen", "https://aiagentcycle.com/nl/nieuwsbrief-bevestigen/")],
        "aac_case": [_item(744, "mercabilis", "https://aiagentcycle.com/nl/cases/mercabilis/", excerpt="<p>Webshop en Exact</p>")],
        "aac_solution": [],
        "aac_icp": [_item(34, "accountants", "https://aiagentcycle.com/en/for/accounting-firms/")],
    }

    def fetch(url: str):
        kind = url.split("/wp/v2/")[1].split("?")[0]
        if "page=1&" in url:
            return _page(data[kind], kind)
        return 400, "application/json", b'{"code":"rest_post_invalid_page_number"}', url

    items = collect(fetch)
    assert {i["id"]: i["type"] for i in items} == {9: "article", 907: "integration", 894: "page", 744: "case", 34: "sector"}
    assert "author" not in items[0]
    report = publish(tmp_path, items, tmp_path / "sync-report.txt")
    assert "added 5" in report and "types article=1 case=1 integration=1 page=1 sector=1" in report and "finished " in report
    text = (tmp_path / "kb" / "744-mercabilis.md").read_text(encoding="utf-8")
    assert "type: case" in text and "summary: Webshop en Exact" in text and "lang: nl" in text and "author" not in text
    assert "lang: en" in (tmp_path / "kb" / "34-accountants.md").read_text(encoding="utf-8")
    again = publish(tmp_path, items, tmp_path / "sync-report.txt")
    assert "changed 0" in again and "unchanged 5" in again
    items[0]["content"] = {"rendered": "<p>Nieuwe kennis</p>"}
    assert "changed 1" in publish(tmp_path, items, tmp_path / "sync-report.txt")


def test_thin_template_pages_use_main_html():
    from sync.aac_mcp_sync import fill_thin

    long = "<p>" + "Tekst over 190 systemen en hoe ze koppelen. " * 10 + "</p>"
    items = [_item(894, "koppelingen", "https://aiagentcycle.com/nl/koppelingen/", content=""),
             _item(20, "prijzen", "https://aiagentcycle.com/nl/prijzen/", content=long),
             _item(6, "home", "https://aiagentcycle.com/nl/", content="")]
    seen = []

    def fetch(url, accept="application/json"):
        seen.append(url)
        if url.endswith("/koppelingen/"):
            return 200, "text/html; charset=UTF-8", f"<header>Menu</header><main id='m'>{long}</main><footer>Voet</footer>".encode(), url
        return 403, "text/html", b"blocked", url

    assert fill_thin(items, fetch) == 1
    assert "190 systemen" in html_to_text(items[0]["content"]["rendered"]) and "Menu" not in items[0]["content"]["rendered"]
    assert items[2]["content"]["rendered"] == "" and "https://aiagentcycle.com/nl/prijzen/" not in seen


CATALOG_HTML = """
<button class="aac-kop-filter" data-dom="">Alles <span class="aac-kop-filter__tal">2</span></button>
<button class="aac-kop-filter aac-kop-filter--administratie" data-dom="administratie">Geld &amp; administratie <span>1</span></button>
<button class="aac-kop-filter aac-kop-filter--data" data-dom="data">Data, servers &amp; AI <span>1</span></button>
<section class="aac-kop-domein" data-dom="administratie"><section class="aac-kop-categorie" data-cat="boekhouding">
<h3 class="aac-kop-categorie__kop">Boekhouding en ERP koppelen <span class="aac-kop-categorie__tal">1</span></h3>
<ul><li class="aac-kop-tegel aac-kop-tegel--productie" data-koppeling="Exact Online" data-oss="0" data-naam="exact online">
<div class="aac-kop-tegel__kop"><span class="aac-kop-logo aac-kop-logo--mono" aria-hidden="true">EO</span><h4>Exact Online</h4>
<span class="aac-kop-label aac-kop-label--productie">In productie</span></div>
<p>Orders, artikelen en prijzen synchroniseren.</p><p class="aac-kop-tegel__hoe">Via de API, door mij gebouwd</p>
<a class="aac-home-link" href="https://aiagentcycle.com/nl/exact-online-koppelen-n8n/">Meer<span class="screen-reader-text"> met Exact</span> →</a></li></ul>
</section></section>
<section class="aac-kop-domein" data-dom="data"><section class="aac-kop-categorie" data-cat="vector">
<h3 class="aac-kop-categorie__kop">Vector databases <span>1</span></h3>
<ul><li class="aac-kop-tegel aac-kop-tegel--standaard" data-koppeling="Qdrant" data-oss="1" data-naam="qdrant">
<div class="aac-kop-tegel__kop"><img class="aac-kop-logo" src="x.svg" alt=""><h4>Qdrant</h4><span class="aac-kop-label">Standaard</span></div>
<p>Vectoren opslaan.</p><p class="aac-kop-tegel__licentie"><span class="aac-kop-oss">Open source</span> Apache-2.0</p></li></ul>
</section></section>
"""


def test_catalog_parses_cards_and_checks_count(tmp_path: Path):
    from sync.aac_mcp_sync import parse_catalog, refresh_catalog

    data = parse_catalog(CATALOG_HTML)
    assert data["total_on_page"] == 2 and data["domains"] == {"administratie": "Geld & administratie", "data": "Data, servers & AI"}
    exact, qdrant = data["items"]
    assert exact == {"name": "Exact Online", "status": "productie", "open_source": False, "domain": "administratie",
                     "category": "Boekhouding en ERP koppelen", "category_id": "boekhouding", "description": "Orders, artikelen en prijzen synchroniseren.",
                     "how": "Via de API, door mij gebouwd", "url": "https://aiagentcycle.com/nl/exact-online-koppelen-n8n/",
                     "status_label": "In productie", "domain_label": "Geld & administratie"}
    assert qdrant["open_source"] is True and qdrant["license"] == "Apache-2.0" and qdrant["category"] == "Vector databases"
    assert "EO" not in html_to_text(CATALOG_HTML) and "Exact Online" in html_to_text(CATALOG_HTML)

    def page(url, accept="application/json"):
        return 200, "text/html", CATALOG_HTML.encode(), url

    # Minder dan 100 tegels: de vorige versie blijft staan.
    assert "nl=oud" in refresh_catalog(tmp_path, page) and not (tmp_path / "integrations.nl.json").exists()
    import sync.aac_mcp_sync as s

    old = s.CATALOG_MIN
    s.CATALOG_MIN = 1
    try:
        assert refresh_catalog(tmp_path, page) == "integrations nl=2 en=2\n"
        assert json.loads((tmp_path / "integrations.en.json").read_text(encoding="utf-8"))["count"] == 2
        broken = CATALOG_HTML.replace('Alles <span class="aac-kop-filter__tal">2', 'Alles <span class="aac-kop-filter__tal">3')
        assert "nl=oud(2 tegels, pagina zegt 3)" in refresh_catalog(tmp_path, lambda u, a="": (200, "text/html", broken.encode(), u))
    finally:
        s.CATALOG_MIN = old


def test_publish_refuses_mass_removal(tmp_path: Path):
    many = [{"id": n, "slug": f"p{n}", "type": "page", "link": f"https://aiagentcycle.com/nl/p{n}/",
             "title": {"rendered": "T"}, "content": {"rendered": "x"}, "excerpt": {"rendered": ""}, "modified": ""} for n in range(30)]
    publish(tmp_path, many, tmp_path / "r.txt")
    with pytest.raises(FailClosed, match="te veel verdwenen"):
        publish(tmp_path, many[:10], tmp_path / "r.txt")
    assert len(list((tmp_path / "kb").glob("*.md"))) == 30


def test_faq_from_json_ld_and_keeps_old_on_failure(tmp_path: Path):
    entries = [{"@type": "Question", "name": f"Vraag {n}?", "acceptedAnswer": {"@type": "Answer", "text": f"<p>Antwoord {n}</p>"}} for n in range(6)]
    page = '<script type="application/ld+json">' + json.dumps({"@graph": [{"@type": "FAQPage", "mainEntity": entries}]}) + "</script>"
    assert faq_items(page)[0] == {"id": "faq-1", "q": "Vraag 0?", "a": "Antwoord 0"}

    def good(url, accept="application/json"):
        return 200, "text/html; charset=UTF-8", page.encode(), url

    assert refresh_faq(tmp_path, good) == "faq nl=6 en=6\n"
    before = (tmp_path / "faq.nl.json").read_text(encoding="utf-8")

    def broken(url, accept="application/json"):
        return 403, "text/html", b"blocked", url

    assert "nl=oud" in refresh_faq(tmp_path, broken)
    assert (tmp_path / "faq.nl.json").read_text(encoding="utf-8") == before
