"""Agent-leesbare bestanden op mcp.aiagentcycle.com, uit dezelfde kennisbank als de MCP-tools.

/llms.txt is een korte index, /llms-full.txt de volledige tekst, /md/{id}.md één document als Markdown.
Server Card en ai-catalog maken de MCP-server vindbaar; de Registry-vermelding komt uit registry_server_json().
"""

from __future__ import annotations

import hashlib
import json

from aac_mcp import __version__
from aac_mcp.kb import Doc, Index

BASE = "https://mcp.aiagentcycle.com"
MCP_URL = f"{BASE}/mcp"
SITE = "https://aiagentcycle.com"
SERVER_NAME = "com.aiagentcycle/aiagentcycle"
# Registry en Server Card staan maximaal 100 tekens toe.
DESCRIPTION = "Read-only facts on AIAgentCycle: n8n automation, AI agents, integrations, prices, cases (NL/EN)."
PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
assert len(DESCRIPTION) <= 100
# Het logo van aiagentcycle.com, door deze server zelf geserveerd zodat een wijziging in WordPress het niet breekt.
ICONS = [
    {"src": f"{BASE}/icon-512.png", "mimeType": "image/png", "sizes": ["512x512"]},
    {"src": f"{BASE}/icon-150.png", "mimeType": "image/png", "sizes": ["150x150"]},
]

TYPE_HEADINGS = {
    "nl": {"page": "Pagina's", "solution": "Oplossingen", "sector": "Sectoren", "integration": "Koppelingen",
           "case": "Cases", "article": "Kennisbank"},
    "en": {"page": "Pages", "solution": "Solutions", "sector": "Sectors", "integration": "Integrations",
           "case": "Case studies", "article": "Knowledge base"},
}
ORDER = ("page", "solution", "sector", "case", "integration", "article")


def server_card() -> dict:
    """SEP-2127 Server Card. Bewust zonder toollijst; die komt uit tools/list."""
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
        "name": SERVER_NAME,
        "title": "AIAgentCycle",
        "version": __version__,
        "description": DESCRIPTION,
        "websiteUrl": SITE,
        "icons": ICONS,
        "remotes": [{"type": "streamable-http", "url": MCP_URL, "supportedProtocolVersions": PROTOCOL_VERSIONS}],
    }


def registry_server_json() -> dict:
    """server.json voor het officiële MCP Registry (schema 2025-12-11)."""
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": SERVER_NAME,
        "title": "AIAgentCycle",
        "description": DESCRIPTION,
        "version": __version__,
        "websiteUrl": SITE,
        "icons": ICONS,
        "remotes": [{"type": "streamable-http", "url": MCP_URL}],
    }


def ai_catalog() -> dict:
    return {
        "specVersion": "1.0",
        "entries": [
            {
                "identifier": "urn:air:aiagentcycle.com:mcp:aiagentcycle",
                "type": "application/mcp-server-card+json",
                "url": f"{MCP_URL}/server-card",
            }
        ],
    }


def stable_json(value: dict) -> tuple[str, str]:
    body = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    return body, '"' + hashlib.sha256(body.encode("utf-8")).hexdigest()[:32] + '"'


def md_url(doc: Doc) -> str:
    return f"{BASE}/md/{doc.id}.md"


def document_markdown(doc: Doc) -> str:
    lines = [
        f"# {doc.title}",
        "",
        f"Source: {doc.link}",
        f"Type: {doc.type} · Language: {doc.lang} · Last modified: {doc.modified or 'unknown'}",
        "",
        doc.text.strip(),
        "",
    ]
    return "\n".join(lines)


def _entry(doc: Doc) -> str:
    summary = f": {doc.summary}" if doc.summary else ""
    return f"- [{doc.title}]({doc.link}) ([Markdown]({md_url(doc)})){summary}"


STATUS_WORDS = {
    "en": {"productie": "in production", "standaard": "n8n built-in", "maatwerk": "custom"},
    "nl": {"productie": "in productie", "standaard": "standaard n8n", "maatwerk": "maatwerk"},
}


def catalog_lines(catalog: dict) -> list[str]:
    """Alle systemen uit het koppelingenoverzicht, per domein en categorie, één regel per systeem."""
    if not catalog.get("items"):
        return []
    lang = catalog.get("lang", "en")
    words = STATUS_WORDS.get(lang, STATUS_WORDS["en"])
    title = "Integrations" if lang == "en" else "Koppelingen"
    out = [f"## {title}: {len(catalog['items'])} systems ({catalog.get('source', '')})", ""]
    legend = ", ".join(f"{v} = {k}" for k, v in words.items())
    out += [f"Status: {legend}. Open-source systems show their license.", ""]
    current = None
    for item in catalog["items"]:
        group = f"{item.get('domain_label', item.get('domain', ''))} / {item.get('category', '')}"
        if group != current:
            out += ["", f"### {group}"]
            current = group
        extra = [words.get(item.get("status", ""), item.get("status", ""))]
        if item.get("license"):
            extra.append(f"open source, {item['license']}")
        line = f"- {item['name']} ({'; '.join(extra)})"
        if item.get("description"):
            line += f": {item['description']}"
        if item.get("url"):
            line += f" {item['url']}"
        out.append(line)
    return out + [""]


def llms_index(index: Index, profile: dict, contact: dict, catalog: dict | None = None) -> str:
    out = [
        "# AIAgentCycle",
        "",
        f"> {profile.get('summary', '')}",
        "",
        f"- Company: {profile.get('legal_name', '')}, {profile.get('location', '')}. Founder: {profile.get('founder', '')}.",
        f"- Website: {SITE}/nl/ (Dutch, primary) and {SITE}/en/ (English).",
        f"- Contact: {contact.get('email', '')} · {contact.get('phone', '')} · free assessment: {contact.get('scan', '')}",
        f"- Prices and packages: {SITE}/nl/prijzen/ ({SITE}/en/pricing/); also via the MCP tool list_services.",
        "",
        "## For AI agents",
        f"- [MCP server]({MCP_URL}): read-only, Streamable HTTP, no login. Tools: search_knowledge_base, get_document,"
        " list_documents, list_integrations, list_services, get_service, list_cases, get_faq, get_company_profile,"
        " get_contact_info.",
        f"- [Server Card]({MCP_URL}/server-card) · [AI catalog]({BASE}/.well-known/ai-catalog.json)",
        f"- [Full text]({BASE}/llms-full.txt): every page, solution, sector, case, integration and article in one file.",
        f"- Mirrors {SITE}, refreshed every hour. {len(index.docs)} documents, newest change {index.newest() or 'unknown'}.",
        "",
        *catalog_lines(catalog or {}),
    ]
    for lang in ("nl", "en"):
        out += [f"# {'Nederlands' if lang == 'nl' else 'English'}", ""]
        for type_ in ORDER:
            docs = index.by_lang(lang, type_)
            if not docs:
                continue
            out += [f"## {TYPE_HEADINGS[lang][type_]}", *(_entry(d) for d in docs), ""]
    return "\n".join(out)


def llms_full(index: Index, catalog: dict | None = None) -> str:
    out = [
        "# AIAgentCycle: full text for AI agents",
        "",
        f"Mirror of {SITE}, {len(index.docs)} documents, newest change {index.newest() or 'unknown'}. MCP server: {MCP_URL}",
        "",
        *catalog_lines(catalog or {}),
    ]
    for lang in ("nl", "en"):
        for type_ in ORDER:
            for doc in index.by_lang(lang, type_):
                out += ["---", "", document_markdown(doc)]
    return "\n".join(out)
