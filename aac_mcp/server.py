"""Nine read-only tools plus agent-readable files. Descriptions stay in this file. No shell, no URL arguments."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from pydantic import Field

from aac_mcp import __version__, docs
from aac_mcp import kb as kbindex
from aac_mcp.content import load_json, public_obj, services
from aac_mcp.jsonlog import write_call
from aac_mcp.search import fold

READONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
MAX_DOC_CHARS = 45_000
STATUSES = ("productie", "standaard", "maatwerk")
STATUS_LEGEND = {
    "nl": {"productie": "draait al bij AIAgentCycle of een klant", "standaard": "n8n heeft er een ingebouwde koppeling voor",
           "maatwerk": "via API, export, database of schermautomatisering"},
    "en": {"productie": "already running in production at AIAgentCycle or a client", "standaard": "n8n has a built-in node for it",
           "maatwerk": "custom, via API, export, database or screen automation"},
}
SYNC_STALE_SECONDS = 3 * 3600

INSTRUCTIONS = (
    "Read-only knowledge of AIAgentCycle (aiagentcycle.com), a Dutch company that builds workflow automation, "
    "system integrations and AI agents on self-hosted n8n for small and medium-sized businesses. "
    "Content mirrors the website in Dutch (nl, primary) and English (en) and is refreshed every hour. "
    "Start with search_knowledge_base or list_documents, then read a full page with get_document. "
    "Which systems can be connected (190, with status and open-source license): list_integrations. "
    "Prices: list_services (each price is checked against the live pricing page; price_verified=false means: "
    "read the pricing page with get_document). Cite the url of each document you use. "
    "This server cannot send messages or book appointments; point people to get_contact_info."
)


def content_root() -> Path:
    return Path(os.environ.get("AAC_MCP_CONTENT", "/srv/mcp-content"))


def log_path() -> Path:
    return Path(os.environ.get("AAC_MCP_LOG", "/var/log/mcp/toolcalls.jsonl"))


def sync_report_path() -> Path:
    return Path(os.environ.get("AAC_MCP_SYNC_LOG", "/var/log/mcp/sync-report.txt"))


def origin_check_enabled() -> bool:
    return os.environ.get("AAC_MCP_ORIGIN_CHECK", "1") != "0"


def _request_meta() -> tuple[str, str]:
    try:
        from fastmcp.server.dependencies import get_http_request

        request = get_http_request()
    except Exception:
        return "", ""
    if request is None:
        return "", ""
    headers = getattr(request, "headers", {}) or {}
    return headers.get("user-agent", "") or "", headers.get("mcp-name", "") or ""


def _finish(tool: str, args: dict, started: float, status: str, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    user_agent, mcp_name = _request_meta()
    write_call(
        log_path(),
        tool=tool,
        args=args,
        status=status,
        duration_ms=int((time.monotonic() - started) * 1000),
        nbytes=len(text.encode("utf-8")),
        user_agent=user_agent,
        mcp_name=mcp_name,
    )
    if status == "error":
        # Een fout moet als isError bij de client aankomen, niet als gewoon antwoord.
        from fastmcp.exceptions import ToolError

        raise ToolError(text)
    return payload


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def verified(index: kbindex.Index, page_id, strings: list) -> bool | None:
    """Staat elke tekst nog letterlijk op de bronpagina? None als er niets te controleren valt."""
    if not strings:
        return None
    doc = index.docs.get(page_id) if isinstance(page_id, int) else None
    if doc is None:
        return False
    hay = _norm(doc.text)
    return all(_norm(str(s)) in hay for s in strings)


def _lang_error(lang) -> str | None:
    return None if lang in {"nl", "en"} else "lang must be nl or en"


def _type_error(type_) -> str | None:
    if type_ in ("", None) or type_ in kbindex.TYPES:
        return None
    return f"type must be empty or one of: {', '.join(kbindex.TYPES)}"


def _priced(index: kbindex.Index, data: dict, item: dict) -> dict:
    item = dict(item)
    item["price_verified"] = verified(index, data.get("verify_page_id"), item.pop("verify", []))
    return item


# Elk argument krijgt een beschrijving en, waar de waarden vastliggen, een enum in het schema: agents kiezen
# tools en waarden op basis hiervan. De controle zelf blijft in de code, zodat foutmeldingen leesbaar blijven.
Lang = Annotated[str, Field(description="Language of the content: nl (Dutch, the primary site language) or en (English).",
                            json_schema_extra={"enum": ["nl", "en"]})]
DocType = Annotated[str, Field(description="Optional filter on document type: article, page, integration, case, solution "
                                           "or sector. Leave empty for all types.",
                               json_schema_extra={"enum": ["", *kbindex.TYPES]})]


def build_mcp():
    from fastmcp import FastMCP
    from mcp.types import Icon

    mcp = FastMCP("aiagentcycle", version=__version__, instructions=INSTRUCTIONS, website_url=docs.SITE,
                  mask_error_details=True, icons=[Icon(**icon) for icon in docs.ICONS])

    @mcp.tool(title="AIAgentCycle company profile", annotations=READONLY)
    def get_company_profile(lang: Lang = "nl") -> dict:
        """Who AIAgentCycle is: summary, legal name, location, founder, focus and approach. lang is nl or en.
        facts_verified tells whether the key facts still appear on the About page."""
        started = time.monotonic()
        args = {"lang": lang}
        if error := _lang_error(lang):
            return _finish("get_company_profile", args, started, "error", error)
        try:
            data = public_obj(load_json(content_root(), f"profile.{lang}.json"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _finish("get_company_profile", args, started, "error", f"profile unreadable: {exc.__class__.__name__}")
        check = data.pop("verify", None) or {}
        index = kbindex.load(content_root())
        data["facts_verified"] = verified(index, check.get("page_id"), check.get("strings", []))
        return _finish("get_company_profile", args, started, "ok", data)

    @mcp.tool(title="AIAgentCycle services and prices", annotations=READONLY)
    def list_services() -> dict:
        """All public services and maintenance packages with indicative prices (excl. VAT, business clients).
        Each price carries price_verified: true if it still appears verbatim on the live pricing page."""
        started = time.monotonic()
        try:
            data = load_json(content_root(), "services.json")
            items = services(content_root())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _finish("list_services", {}, started, "error", f"services unreadable: {exc.__class__.__name__}")
        index = kbindex.load(content_root())
        priced = [_priced(index, data, item) for item in items]
        page = index.docs.get(data.get("verify_page_id"))
        out = {
            "price_terms": data.get("price_terms"),
            "source": data.get("source"),
            "source_en": data.get("source_en"),
            "prices_checked_against": {"url": page.link, "modified": page.modified} if page else None,
            "all_prices_verified": all(item["price_verified"] is not False for item in priced),
            "services": priced,
        }
        if not out["all_prices_verified"]:
            out["warning"] = (
                "One or more prices no longer appear verbatim on the pricing page. "
                f"Read get_document({data.get('verify_page_id')}) for the current prices before quoting them."
            )
        return _finish("list_services", {}, started, "ok", out)

    @mcp.tool(title="One AIAgentCycle service", annotations=READONLY)
    def get_service(
        service_id: Annotated[str, Field(description="Service id exactly as returned by list_services, "
                                                     "for example quick-win, techbeheer or serverbeheer.")],
    ) -> dict:
        """One public service by id (ids come from list_services). An unknown id is an error."""
        started = time.monotonic()
        args = {"service_id": service_id}
        try:
            data = load_json(content_root(), "services.json")
            items = services(content_root())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _finish("get_service", args, started, "error", f"services unreadable: {exc.__class__.__name__}")
        for item in items:
            if item.get("id") == service_id:
                return _finish("get_service", args, started, "ok", _priced(kbindex.load(content_root()), data, item))
        return _finish("get_service", args, started, "error", f"unknown service: {service_id}")

    @mcp.tool(title="Search the AIAgentCycle website", annotations=READONLY)
    def search_knowledge_base(
        query: Annotated[str, Field(description="Search words, 1 to 100 characters, in the language of lang, "
                                                "for example 'Exact Online koppeling' or 'AI agent cost'.")],
        lang: Lang = "nl",
        limit: Annotated[int, Field(description="Maximum number of hits to return, 1 to 10.")] = 5,
        type: DocType = "",
    ) -> dict:
        """Ranked full-text search over every page, solution, sector page, case, integration and article of
        aiagentcycle.com. Any word may match; documents matching more words rank higher. lang is nl or en.
        type optionally narrows to: article, page, integration, case, solution, sector. query max 100 chars,
        limit 1-10. Each hit has an id for get_document and the source url."""
        started = time.monotonic()
        args = {"query": query, "lang": lang, "limit": limit, "type": type}
        if not isinstance(query, str) or len(query) > 100 or len(query.strip()) == 0:
            return _finish("search_knowledge_base", args, started, "error", "query must be 1 to 100 characters")
        if error := _lang_error(lang) or _type_error(type):
            return _finish("search_knowledge_base", args, started, "error", error)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 10:
            return _finish("search_knowledge_base", args, started, "error", "limit must be 1 to 10")
        index = kbindex.load(content_root())
        hits, other_lang = [], 0
        for doc_id, score in index.bm25.search(query, limit=len(index.docs)):
            doc = index.docs[int(doc_id)]
            if type and doc.type != type:
                continue
            if doc.lang != lang:
                other_lang += 1
                continue
            if len(hits) < limit:
                hits.append({**doc.meta(), "score": round(score, 2), "snippet": kbindex.snippet(doc, query)})
        payload = {"hits": hits, "total_documents": len(index.docs)}
        if not hits and other_lang:
            payload["note"] = f"{other_lang} match(es) in the other language; try lang={'en' if lang == 'nl' else 'nl'}."
        return _finish("search_knowledge_base", args, started, "ok", payload)

    @mcp.tool(title="Read one AIAgentCycle page in full", annotations=READONLY)
    def get_document(
        id: Annotated[int, Field(description="Numeric document id from search_knowledge_base or list_documents, "
                                             "for example 20 for the Dutch pricing page.")],
    ) -> dict:
        """Full text (Markdown) of one page, article, case, solution, sector or integration page, with its
        source url, language and last-modified date. Ids come from search_knowledge_base or list_documents."""
        started = time.monotonic()
        args = {"id": id}
        if not isinstance(id, int) or isinstance(id, bool):
            return _finish("get_document", args, started, "error", "id must be an integer")
        doc = kbindex.load(content_root()).docs.get(id)
        if doc is None:
            return _finish("get_document", args, started, "error", f"unknown document: {id}; use list_documents or search_knowledge_base")
        text = doc.text
        truncated = len(text) > MAX_DOC_CHARS
        payload = {**doc.meta(), "markdown_url": docs.md_url(doc), "truncated": truncated,
                   "text": text[:MAX_DOC_CHARS] if truncated else text}
        return _finish("get_document", args, started, "ok", payload)

    @mcp.tool(title="List AIAgentCycle pages", annotations=READONLY)
    def list_documents(lang: Lang = "nl", type: DocType = "") -> dict:
        """Catalogue of the website: id, type, title, url, last-modified date and a one-line summary per
        document. lang is nl or en. type optionally narrows to: article, page, integration, case, solution, sector."""
        started = time.monotonic()
        args = {"lang": lang, "type": type}
        if error := _lang_error(lang) or _type_error(type):
            return _finish("list_documents", args, started, "error", error)
        found = kbindex.load(content_root()).by_lang(lang, type or None)
        payload = {"lang": lang, "type": type or "all", "count": len(found), "documents": [d.meta() for d in found]}
        return _finish("list_documents", args, started, "ok", payload)

    @mcp.tool(title="Systems AIAgentCycle integrates", annotations=READONLY)
    def list_integrations(
        lang: Lang = "nl",
        query: Annotated[str, Field(description="Optional words that must all occur in the name, description, category "
                                                "or license, for example 'twinfield' or 'crm'. Max 100 characters.")] = "",
        domain: Annotated[str, Field(description="Optional domain filter: administratie (finance and admin), verkoop "
                                                 "(customers and sales), samenwerken (work and communication) or data "
                                                 "(data, servers and AI).",
                                     json_schema_extra={"enum": ["", "administratie", "verkoop", "samenwerken", "data"]})] = "",
        status: Annotated[str, Field(description="Optional status filter: productie (running in production), standaard "
                                                 "(n8n built-in node) or maatwerk (custom).",
                                     json_schema_extra={"enum": ["", *STATUSES]})] = "",
        open_source: Annotated[bool | None, Field(description="true for only open-source systems, false for only "
                                                              "proprietary ones; leave out for both.")] = None,
    ) -> dict:
        """The integrations catalogue of aiagentcycle.com (190 systems): name, status, domain, category,
        description, open-source license and a detail-page url where one exists. Status: productie = already
        running in production at AIAgentCycle or a client; standaard = n8n has a built-in node; maatwerk = custom
        via API, export, database or screen automation. Filters: query (name or text, max 100 chars), domain
        (administratie, verkoop, samenwerken, data), status, open_source. lang is nl or en. A system that is not
        listed can usually still be connected through one of those four routes."""
        started = time.monotonic()
        args = {"lang": lang, "query": query, "domain": domain, "status": status, "open_source": open_source}
        if error := _lang_error(lang):
            return _finish("list_integrations", args, started, "error", error)
        if not isinstance(query, str) or len(query) > 100:
            return _finish("list_integrations", args, started, "error", "query must be at most 100 characters")
        if status not in ("", *STATUSES):
            return _finish("list_integrations", args, started, "error", f"status must be empty or one of: {', '.join(STATUSES)}")
        try:
            data = load_json(content_root(), f"integrations.{lang}.json")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _finish("list_integrations", args, started, "error", f"integrations unreadable: {exc.__class__.__name__}")
        domains = data.get("domains", {})
        if domain and domain not in domains:
            return _finish("list_integrations", args, started, "error", f"domain must be empty or one of: {', '.join(domains)}")
        needles = [fold(w) for w in query.split()]
        found = []
        for item in data.get("items", []):
            if (domain and item.get("domain") != domain) or (status and item.get("status") != status):
                continue
            if open_source is not None and item.get("open_source") is not open_source:
                continue
            hay = fold(" ".join(str(item.get(k, "")) for k in ("name", "description", "category", "license", "how")))
            if needles and not all(n in hay for n in needles):
                continue
            found.append(item)
        payload = {
            "lang": lang, "source": data.get("source"), "updated": data.get("updated"),
            "total_systems": len(data.get("items", [])), "count": len(found), "domains": domains,
            "status_legend": STATUS_LEGEND[lang], "integrations": found,
        }
        if not found:
            payload["note"] = ("Not in the catalogue. Systems with an API, an export, a database or a screen can usually be "
                               "connected as custom work; the free assessment checks this (get_contact_info).")
        return _finish("list_integrations", args, started, "ok", payload)

    @mcp.tool(title="AIAgentCycle FAQ", annotations=READONLY)
    def get_faq(lang: Lang = "nl") -> dict:
        """Frequently asked questions about prices, maintenance and approach, verbatim from the pricing page.
        lang is nl or en."""
        started = time.monotonic()
        args = {"lang": lang}
        if error := _lang_error(lang):
            return _finish("get_faq", args, started, "error", error)
        try:
            data = load_json(content_root(), f"faq.{lang}.json")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _finish("get_faq", args, started, "error", f"faq unreadable: {exc.__class__.__name__}")
        return _finish("get_faq", args, started, "ok", data)

    @mcp.tool(title="AIAgentCycle case studies", annotations=READONLY)
    def list_cases(lang: Lang = "nl") -> dict:
        """Published case studies (client and own projects) with title, summary and url. Read one in full with
        get_document. lang is nl or en."""
        started = time.monotonic()
        args = {"lang": lang}
        if error := _lang_error(lang):
            return _finish("list_cases", args, started, "error", error)
        found = kbindex.load(content_root()).by_lang(lang, "case")
        return _finish("list_cases", args, started, "ok", {"count": len(found), "cases": [d.meta() for d in found]})

    @mcp.tool(title="Contact AIAgentCycle", annotations=READONLY)
    def get_contact_info() -> dict:
        """Public contact route: email, phone/WhatsApp, contact page and the free assessment (scan) page.
        This server cannot send messages or book appointments."""
        started = time.monotonic()
        try:
            data = load_json(content_root(), "contact.json")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _finish("get_contact_info", {}, started, "error", f"contact unreadable: {exc.__class__.__name__}")
        return _finish("get_contact_info", {}, started, "ok", public_obj(data))

    return mcp


def last_sync(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("finished "):
                return line.split(" ", 1)[1].strip()
    except OSError:
        return None
    return None


def create_app():
    from starlette.middleware import Middleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from aac_mcp.origin import OriginGuard

    mcp = build_mcp()
    app = mcp.http_app(
        path="/mcp",
        host_origin_protection=False,
        stateless_http=True,
        middleware=[Middleware(OriginGuard, enabled=origin_check_enabled())],
    )

    async def healthz(request):
        index = kbindex.load(content_root())
        synced = last_sync(sync_report_path())
        age = None
        if synced:
            try:
                age = int(time.time() - datetime.strptime(synced, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                age = None
        ok = len(index.docs) > 0 and age is not None and age < SYNC_STALE_SECONDS
        body = {"status": "ok" if ok else "degraded", "version": __version__, "documents": len(index.docs),
                "newest_change": index.newest(), "last_sync": synced, "sync_age_seconds": age}
        return JSONResponse(body, headers={"cache-control": "no-store"})

    app.router.routes.insert(0, Route("/healthz", healthz, methods=["GET"]))
    for route in doc_routes():
        app.router.routes.insert(0, route)
    return app


def doc_routes():
    """Agent-leesbare bestanden: Server Card, ai-catalog, llms.txt, llms-full.txt en Markdown per document."""
    from starlette.responses import PlainTextResponse, RedirectResponse, Response
    from starlette.routing import Route

    rendered: dict = {}
    text_headers = {"cache-control": "public, max-age=900", "access-control-allow-origin": "*"}

    def respond(request, key: tuple, build, media: str):
        index = kbindex.load(content_root())
        cache_key = (index.key, *key)
        if cache_key not in rendered:
            if len(rendered) > 512:
                rendered.clear()
            body = build(index)
            rendered[cache_key] = (body, docs.stable_json({"b": body})[1])
        body, etag = rendered[cache_key]
        headers = {**text_headers, "etag": etag}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return PlainTextResponse(body, media_type=media, headers=headers)

    def _json(name: str) -> dict:
        try:
            return public_obj(load_json(content_root(), name))
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    async def llms_txt(request):
        catalog = _json("integrations.en.json")
        return respond(request, ("llms", catalog.get("updated"), catalog.get("count")),
                       lambda index: docs.llms_index(index, _json("profile.en.json"), _json("contact.json"), catalog),
                       "text/plain; charset=utf-8")

    async def llms_full_txt(request):
        catalog = _json("integrations.nl.json")
        return respond(request, ("full", catalog.get("updated"), catalog.get("count")),
                       lambda index: docs.llms_full(index, catalog), "text/plain; charset=utf-8")

    async def markdown_doc(request):
        name = request.path_params["name"]
        if not name.endswith(".md") or not name[:-3].isdigit():
            return PlainTextResponse("not found", status_code=404)
        doc_id = int(name[:-3])
        if kbindex.load(content_root()).docs.get(doc_id) is None:
            return PlainTextResponse("not found", status_code=404)
        return respond(request, ("md", doc_id), lambda index: docs.document_markdown(index.docs[doc_id]),
                       "text/markdown; charset=utf-8")

    async def robots(request):
        body = f"User-agent: *\nAllow: /\n\n# Index for AI agents: {docs.BASE}/llms.txt\n"
        return PlainTextResponse(body, headers={"cache-control": "public, max-age=86400"})

    async def root(request):
        return RedirectResponse(f"{docs.BASE}/llms.txt", status_code=302)

    card_cors = {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET, HEAD, OPTIONS",
        "cache-control": "public, max-age=3600",
    }

    def static_json(value: dict, media: str):
        body, etag = docs.stable_json(value)

        async def handler(request):
            headers = {**card_cors, "etag": etag}
            if request.method == "OPTIONS":
                return Response(status_code=204, headers=headers)
            if request.headers.get("if-none-match") == etag:
                return Response(status_code=304, headers=headers)
            return Response(body, media_type=media, headers=headers)

        return handler

    static_dir = Path(__file__).parent / "static"

    def icon(name: str):
        body = (static_dir / name).read_bytes()

        async def handler(request):
            return Response(body, media_type="image/png",
                            headers={"cache-control": "public, max-age=86400", "access-control-allow-origin": "*"})

        return handler

    return [
        Route("/icon-512.png", icon("icon-512.png"), methods=["GET", "HEAD"]),
        Route("/icon-150.png", icon("icon-150.png"), methods=["GET", "HEAD"]),
        Route("/mcp/server-card", static_json(docs.server_card(), "application/mcp-server-card+json"), methods=["GET", "HEAD", "OPTIONS"]),
        Route("/.well-known/ai-catalog.json", static_json(docs.ai_catalog(), "application/ai-catalog+json"), methods=["GET", "HEAD", "OPTIONS"]),
        Route("/llms.txt", llms_txt, methods=["GET", "HEAD"]),
        Route("/llms-full.txt", llms_full_txt, methods=["GET", "HEAD"]),
        Route("/md/{name}", markdown_doc, methods=["GET", "HEAD"]),
        Route("/robots.txt", robots, methods=["GET", "HEAD"]),
        Route("/", root, methods=["GET", "HEAD"]),
    ]
