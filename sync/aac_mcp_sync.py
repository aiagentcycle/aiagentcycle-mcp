"""Fail-closed pull of all public content from aiagentcycle.com into kb/.

Haalt artikelen, pagina's, cases, oplossingen en sectorpagina's op via de WordPress REST API,
zet ze om naar Markdown met een YAML-kop, en ververst daarna de FAQ uit de JSON-LD van de
prijzenpagina's. De kennisbank wordt alleen in zijn geheel vervangen; bij twijfel blijft de oude staan.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

HOST = "aiagentcycle.com"
USER_AGENT = "aac-mcp-sync/1.1 (+https://mcp.aiagentcycle.com)"
FIELDS = "id,slug,modified,link,title,content,excerpt"
ALLOW = {"id", "slug", "modified", "link", "title", "content", "excerpt"}
MAX_ITEM = 2 * 1024 * 1024
MAX_ITEMS = 500
MAX_SECONDS = 90
# REST-basis en het type dat agents te zien krijgen.
KINDS = (
    ("posts", "article"),
    ("pages", "page"),
    ("aac_case", "case"),
    ("aac_solution", "solution"),
    ("aac_icp", "sector"),
)
# Bevestigings- en bedankpagina's zijn geen kennis.
SKIP_SLUGS = frozenset({"newsletter-confirm", "nieuwsbrief-bevestigen", "afspraak-bevestigd", "booked", "gepland"})
# Verdwijnt in één keer meer dan dit deel van de kennisbank, dan is de site waarschijnlijk half kapot.
MAX_DROP = 0.4
FAQ_PAGES = {"nl": "https://aiagentcycle.com/nl/prijzen/", "en": "https://aiagentcycle.com/en/pricing/"}
FAQ_MIN_ITEMS = 5


class FailClosed(Exception):
    pass


BLOCK = {
    "p", "div", "br", "section", "article", "aside", "header", "footer", "main", "figure", "figcaption",
    "blockquote", "table", "thead", "tbody", "ul", "ol", "dl", "dt", "dd", "details", "summary", "hr",
}
HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}
SKIP = {"script", "style", "noscript", "template", "svg", "form", "select", "nav", "iframe"}
# Na </strong>, </a> enz. alleen een spatie als er direct een woord volgt: "5 uur per weekaan" wordt
# "5 uur per week aan", maar "<strong>Let op</strong>:" blijft "Let op:".
SOFT_END = {"a", "strong", "b", "em", "i", "button"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SOFT = "\x00"
SOFT_SPACE = re.compile("\x00(?=[\\w€(])")


class TextExtractor(HTMLParser):
    """HTML naar leesbare Markdown-achtige tekst: koppen, lijstpunten en tabelcellen blijven herkenbaar."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.cell = 0
        self.hidden: tuple[str, int] | None = None

    def handle_starttag(self, tag, attrs):
        if self.hidden:
            if tag == self.hidden[0]:
                self.hidden = (tag, self.hidden[1] + 1)
            return
        if tag in SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if ("aria-hidden", "true") in attrs and tag not in VOID:
            # Decoratie (logo-initialen, iconen) hoort niet in de leestekst.
            self.hidden = (tag, 1)
            return
        if tag in HEADINGS:
            self.parts.append(f"\n\n{HEADINGS[tag]} ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "tr":
            self.parts.append("\n")
            self.cell = 0
        elif tag in {"td", "th"}:
            self.parts.append(" | " if self.cell else "")
            self.cell += 1
        elif tag in BLOCK:
            self.parts.append("\n")
        elif tag in {"span", "small", "label"}:
            # <strong>€250</strong><span>per maand</span> mag niet "€250per maand" worden.
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[0]:
                self.hidden = (tag, self.hidden[1] - 1) if self.hidden[1] > 1 else None
            return
        if tag in SKIP:
            if self.skip:
                self.skip -= 1
            return
        if self.skip:
            return
        if tag in HEADINGS:
            self.parts.append("\n")
        elif tag in SOFT_END:
            self.parts.append(SOFT)

    def handle_data(self, data):
        if not self.skip and not self.hidden:
            self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = TextExtractor()
    parser.feed(value or "")
    parser.close()
    joined = SOFT_SPACE.sub(" ", "".join(parser.parts)).replace(SOFT, "")
    lines = []
    for line in joined.splitlines():
        line = " ".join(line.split())
        if line in {"-", "#", "##", "###", "####"}:
            continue
        if line:
            lines.append(line)
    out = []
    for line in lines:
        # Een lege regel vóór elke kop houdt de Markdown leesbaar.
        if line.startswith("#") and out:
            out.append("")
        out.append(line)
        if line.startswith("#"):
            out.append("")
    return "\n".join(out).strip()


def one_line(text: str, limit: int = 300) -> str:
    text = " ".join(text.replace("#", " ").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def rendered(field) -> str:
    if isinstance(field, dict):
        return str(field.get("rendered") or "")
    if field is None:
        return ""
    return str(field)


def check_response(status: int, content_type: str, body: bytes, final_url: str, *, check_content_type: bool = True) -> list:
    if status != 200:
        raise FailClosed(f"status {status}")
    host = urlparse(final_url).hostname
    if host != HOST:
        raise FailClosed(f"host {host}")
    if len(body) > MAX_ITEM:
        raise FailClosed("item te groot")
    if check_content_type and not content_type.lower().startswith("application/json"):
        raise FailClosed(f"content-type {content_type}")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FailClosed("geen json") from exc
    if not isinstance(data, list):
        raise FailClosed("geen array")
    return data


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FailClosed(f"redirect {code} {newurl}")


def fetch_url(url: str, accept: str = "application/json") -> tuple[int, str, bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=20) as response:
            body = response.read(MAX_ITEM + 1)
            ctype = response.headers.get("Content-Type", "")
            return response.status, ctype, body, response.geturl()
    except FailClosed:
        raise
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_ITEM + 1)
        return exc.code, exc.headers.get("Content-Type", ""), body, url


def keep(item: dict) -> dict:
    return {key: item.get(key) for key in ALLOW}


def lang_of(link: str) -> str:
    path = urlparse(link or "").path
    if path.startswith("/en/") or path == "/en":
        return "en"
    return "nl"


def type_of(base_type: str, link: str) -> str:
    path = urlparse(link or "").path
    if base_type == "page" and re.match(r"^/(nl/koppelingen|en/integrations)/[^/]+/$", path):
        return "integration"
    return base_type


def to_markdown(item: dict) -> str:
    title = html_to_text(rendered(item.get("title"))).replace("\n", " ") or str(item.get("slug") or "")
    body = html_to_text(rendered(item.get("content")))
    excerpt = html_to_text(rendered(item.get("excerpt")))
    text = body or excerpt
    summary = one_line(excerpt or body)
    link = str(item.get("link") or "")
    return (
        "---\n"
        f"id: {item.get('id')}\n"
        f"slug: {item.get('slug')}\n"
        f"type: {item.get('type') or 'page'}\n"
        f"modified: {item.get('modified')}\n"
        f"link: {link}\n"
        f"lang: {lang_of(link)}\n"
        f"title: {one_line(title, 200)}\n"
        f"summary: {summary}\n"
        "---\n\n"
        f"# {title}\n\n"
        f"{text}\n"
    )


def slug_ok(slug: str) -> bool:
    if not slug or len(slug) > 180:
        return False
    return all(ch.isalnum() or ch in "-_" for ch in slug)


def collect(fetch, *, check_content_type: bool = True, now=time.monotonic, kinds=KINDS) -> list[dict]:
    started = now()
    items: list[dict] = []
    for kind, base_type in kinds:
        page = 1
        while True:
            if now() - started > MAX_SECONDS:
                raise FailClosed("timeout")
            if len(items) > MAX_ITEMS:
                raise FailClosed("te veel items")
            url = f"https://{HOST}/wp-json/wp/v2/{kind}?per_page=50&page={page}&_fields={FIELDS}"
            status, ctype, body, final_url = fetch(url)
            try:
                batch = check_response(status, ctype, body, final_url, check_content_type=check_content_type)
            except FailClosed as exc:
                if page > 1 and "status 400" in str(exc):
                    break
                raise
            if not batch:
                break
            for raw in batch:
                if not isinstance(raw, dict):
                    raise FailClosed("item geen object")
                item = keep(raw)
                if not slug_ok(str(item.get("slug") or "")):
                    raise FailClosed("slug")
                if item["slug"] in SKIP_SLUGS:
                    continue
                item["type"] = type_of(base_type, str(item.get("link") or ""))
                items.append(item)
                if len(items) > MAX_ITEMS:
                    raise FailClosed("te veel items")
            if len(batch) < 50:
                break
            page += 1
    if not items:
        raise FailClosed("leeg")
    return items


THIN_CHARS = 200
MAX_FALLBACK = 20
MAIN = re.compile(r"<main\b[^>]*>(.*)</main>", re.S | re.I)


def fill_thin(items: list[dict], fetch=fetch_url) -> int:
    """Pagina's die uit een template komen (home, overzichten) hebben geen tekst in de REST API.
    Voor die pagina's wordt de <main> van de gepubliceerde HTML gebruikt. Mislukt dat, dan blijft het item zoals het was."""
    filled = 0
    for item in items:
        if filled >= MAX_FALLBACK or len(html_to_text(rendered(item.get("content")))) >= THIN_CHARS:
            continue
        link = str(item.get("link") or "")
        if urlparse(link).hostname != HOST:
            continue
        try:
            status, ctype, body, final_url = fetch(link, "text/html")
        except (FailClosed, OSError):
            continue
        if status != 200 or urlparse(final_url).hostname != HOST or not ctype.lower().startswith("text/html"):
            continue
        match = MAIN.search(body.decode("utf-8", "replace"))
        if match and len(html_to_text(match.group(1))) >= THIN_CHARS:
            item["content"] = {"rendered": match.group(1)}
            filled += 1
    return filled


def publish(root: Path, items: list[dict], log_file: Path) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    staging = root / f".staging-{stamp}"
    if staging.exists():
        raise FailClosed("staging bestaat")
    kb = root / "kb"
    old = {path.name for path in kb.glob("*.md")} if kb.is_dir() else set()
    names = [f"{item.get('id')}-{item.get('slug')}.md" for item in items]
    if len(old) >= 20 and len(set(names)) < len(old) * (1 - MAX_DROP):
        raise FailClosed(f"te veel verdwenen: {len(old)} -> {len(set(names))}")
    staging.mkdir(parents=True)
    total = 0
    for name, item in zip(names, items):
        text = to_markdown(item)
        total += len(text.encode("utf-8"))
        (staging / name).write_text(text, encoding="utf-8")
    if not names or total <= 0:
        raise FailClosed("staging leeg")
    prev = root / ".prev"
    changed = 0
    if kb.is_dir():
        # Alleen echte inhoudswijzigingen tellen, niet elk bestand dat er al was.
        for name in set(names) & old:
            try:
                if (staging / name).read_bytes() != (kb / name).read_bytes():
                    changed += 1
            except OSError:
                changed += 1
        if prev.exists():
            import shutil

            shutil.rmtree(prev)
        kb.rename(prev)
    staging.rename(kb)
    new = set(names)
    by_type: dict[str, int] = {}
    for item in items:
        by_type[item["type"]] = by_type.get(item["type"], 0) + 1
    report = (
        f"added {len(new - old)}\n"
        f"changed {changed}\n"
        f"unchanged {len(new & old) - changed}\n"
        f"removed {len(old - new)}\n"
        f"total {len(new)}\n"
        f"types {' '.join(f'{k}={v}' for k, v in sorted(by_type.items()))}\n"
        f"finished {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
    )
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(report, encoding="utf-8")
    return report


ZW = re.compile("[​‌‍⁠﻿­]")


def faq_items(page_html: str) -> list[dict]:
    """Vraag en antwoord letterlijk uit de FAQPage-JSON-LD, zonder herschrijven."""
    items = []
    for block in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page_html, re.S):
        try:
            data = json.loads(ZW.sub("", block))
        except json.JSONDecodeError:
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            if "FAQPage" not in (types if isinstance(types, list) else [types]):
                continue
            for entry in node.get("mainEntity", []):
                q = " ".join(html.unescape(ZW.sub("", entry.get("name", ""))).split())
                a = html.unescape(re.sub(r"<[^>]+>", " ", ZW.sub("", (entry.get("acceptedAnswer") or {}).get("text", ""))))
                a = " ".join(a.split())
                if q and a:
                    items.append({"id": f"faq-{len(items) + 1}", "q": q, "a": a})
    return items


def refresh_faq(root: Path, fetch=fetch_url) -> str:
    """Ververst faq.{nl,en}.json. Mislukt het, dan blijft de vorige versie staan (geen harde fout)."""
    results = []
    for lang, url in FAQ_PAGES.items():
        try:
            status, ctype, body, final_url = fetch(url, "text/html")
            if status != 200 or urlparse(final_url).hostname != HOST or not ctype.lower().startswith("text/html"):
                raise FailClosed(f"status {status} {ctype}")
            items = faq_items(body.decode("utf-8", "replace"))
            if len(items) < FAQ_MIN_ITEMS:
                raise FailClosed(f"{len(items)} items")
        except (FailClosed, OSError) as exc:
            results.append(f"{lang}=oud({exc})")
            continue
        doc = {"lang": lang, "status": "published", "source": url, "updated": date.today().isoformat(), "items": items}
        target = root / f"faq.{lang}.json"
        tmp = root / f".faq.{lang}.json.tmp"
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(target)
        results.append(f"{lang}={len(items)}")
    return "faq " + " ".join(results) + "\n"


CATALOG_PAGES = {"nl": "https://aiagentcycle.com/nl/koppelingen/", "en": "https://aiagentcycle.com/en/integrations/"}
CATALOG_MIN = 100


class CatalogParser(HTMLParser):
    """Leest de koppelingentegels (li.aac-kop-tegel) met domein en categorie uit het koppelingenoverzicht."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self.domains: dict[str, str] = {}
        self.total: int | None = None
        self.dom = self.cat = self.cat_title = ""
        self.card: dict | None = None
        self.capture: tuple[str, str, int] | None = None  # (veld, tag, diepte)
        self.buf: list[str] = []

    def _start(self, field: str, tag: str) -> None:
        self.capture, self.buf = (field, tag, 1), []

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        cls = a.get("class", "")
        if self.capture:
            if tag == self.capture[1]:
                self.capture = (self.capture[0], tag, self.capture[2] + 1)
            return
        if tag == "button" and "aac-kop-filter" in cls and "data-dom" in a:
            self._start("filter:" + a["data-dom"], "button")
        elif tag == "section" and "data-dom" in a:
            self.dom = a["data-dom"]
        elif tag == "section" and "data-cat" in a:
            self.cat, self.cat_title = a["data-cat"], ""
        elif tag == "h3" and "aac-kop-categorie__kop" in cls:
            self._start("cat_title", "h3")
        elif tag == "li" and "aac-kop-tegel" in cls and "data-koppeling" in a:
            status = re.search(r"aac-kop-tegel--([a-z]+)", cls)
            self.card = {"name": a["data-koppeling"].strip(), "status": status.group(1) if status else "",
                         "open_source": a.get("data-oss") == "1", "domain": self.dom, "category": self.cat_title,
                         "category_id": self.cat, "description": "", "how": "", "license": "", "url": ""}
        elif self.card is not None:
            if tag == "span" and "aac-kop-label" in cls:
                self._start("status_label", "span")
            elif tag == "p" and "aac-kop-tegel__hoe" in cls:
                self._start("how", "p")
            elif tag == "p" and "aac-kop-tegel__licentie" in cls:
                self._start("license", "p")
            elif tag == "p" and not cls:
                self._start("description", "p")
            elif tag == "a" and a.get("href", "").startswith("https://"):
                self.card["url"] = a["href"]

    def handle_endtag(self, tag):
        if self.capture and tag == self.capture[1]:
            field, _, depth = self.capture
            if depth > 1:
                self.capture = (field, tag, depth - 1)
                return
            text = " ".join("".join(self.buf).split())
            self.capture = None
            if field.startswith("filter:"):
                label, count = re.match(r"^(.*?)\s*(\d+)?$", text).groups()
                if field == "filter:":
                    self.total = int(count) if count else None
                else:
                    self.domains[field[7:]] = label
            elif field == "cat_title":
                self.cat_title = re.sub(r"\s*\d+$", "", text)
            elif self.card is not None:
                if field == "license":
                    text = re.sub(r"^Open source\s*", "", text)
                self.card[field] = text
            return
        if tag == "li" and self.card is not None and not self.capture:
            self.items.append(self.card)
            self.card = None

    def handle_data(self, data):
        if self.capture:
            self.buf.append(data)


def parse_catalog(page_html: str) -> dict:
    parser = CatalogParser()
    parser.feed(page_html)
    parser.close()
    for item in parser.items:
        item["domain_label"] = parser.domains.get(item["domain"], item["domain"])
        for key in [k for k, v in item.items() if v == ""]:
            del item[key]
    return {"total_on_page": parser.total, "domains": parser.domains, "items": parser.items}


def refresh_catalog(root: Path, fetch=fetch_url) -> str:
    """Schrijft integrations.{nl,en}.json. Klopt het aantal niet met de teller op de pagina, dan blijft de vorige versie."""
    results = []
    for lang, url in CATALOG_PAGES.items():
        try:
            status, ctype, body, final_url = fetch(url, "text/html")
            if status != 200 or urlparse(final_url).hostname != HOST or not ctype.lower().startswith("text/html"):
                raise FailClosed(f"status {status} {ctype}")
            data = parse_catalog(body.decode("utf-8", "replace"))
            count = len(data["items"])
            if count < CATALOG_MIN or (data["total_on_page"] and count != data["total_on_page"]):
                raise FailClosed(f"{count} tegels, pagina zegt {data['total_on_page']}")
        except (FailClosed, OSError) as exc:
            results.append(f"{lang}=oud({exc})")
            continue
        doc = {"lang": lang, "source": url, "updated": date.today().isoformat(), "count": count, **data}
        tmp = root / f".integrations.{lang}.json.tmp"
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(root / f"integrations.{lang}.json")
        results.append(f"{lang}={count}")
    return "integrations " + " ".join(results) + "\n"


def main() -> int:
    root = Path(os.environ.get("AAC_MCP_CONTENT", "/srv/mcp-content"))
    log_file = Path(os.environ.get("AAC_MCP_SYNC_LOG", "/var/log/mcp/sync-report.txt"))
    try:
        items = collect(fetch_url)
        filled = fill_thin(items)
        report = publish(root, items, log_file)
    except FailClosed as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    faq = f"html_fallback {filled}\n" + refresh_faq(root) + refresh_catalog(root)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(faq)
    print(report + faq, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
