import asyncio
import json
from pathlib import Path

from aac_mcp.content import MAX_BYTES, cap_text, kb_files
from aac_mcp.jsonlog import args_hash
from aac_mcp.origin import origin_allowed

FRONT = (
    "---\nid: {id}\nslug: {slug}\ntype: {type}\nmodified: 2026-11-02T10:00:00\n"
    "link: https://aiagentcycle.com/{lang}/{slug}/\nlang: {lang}\ntitle: {title}\nsummary: {summary}\n---\n\n# {title}\n\n{body}\n"
)
PRIJZEN = "Quick-win | Vanaf €750 | Eén afgebakend proces\nTechbeheer\n€250 per maand, excl. btw\nOver ons: 300+ automatiseringen"


def _doc(tmp: Path, id: int, slug: str, *, lang="nl", type="page", title="Titel", summary="Samenvatting", body="Tekst"):
    (tmp / "kb" / f"{id}-{slug}.md").write_text(
        FRONT.format(id=id, slug=slug, type=type, lang=lang, title=title, summary=summary, body=body), encoding="utf-8")


def _tree(tmp: Path) -> None:
    (tmp / "kb").mkdir()
    for lang in ("nl", "en"):
        (tmp / f"profile.{lang}.json").write_text(json.dumps(
            {"lang": lang, "status": "published", "name": "AIAgentCycle", "summary": "Automatisering",
             "verify": {"page_id": 20, "strings": ["300+ automatiseringen"]}, "_draft": "weg"}), encoding="utf-8")
    (tmp / "services.json").write_text(json.dumps({
        "verify_page_id": 20,
        "services": [
            {"id": "quick-win", "name": "Quick-win", "price": "Vanaf €750", "verify": ["Quick-win | Vanaf €750"], "internal_notes": "geheim"},
            {"id": "techbeheer", "name": "Techbeheer", "price": "€250 per maand", "verify": ["€250 per maand"]},
            {"id": "training", "name": "Training", "price": "Op aanvraag", "verify": []},
        ]}), encoding="utf-8")
    (tmp / "faq.nl.json").write_text(json.dumps({"lang": "nl", "items": [{"q": "audit", "a": "ja"}]}), encoding="utf-8")
    (tmp / "faq.en.json").write_text(json.dumps({"lang": "en", "items": []}), encoding="utf-8")
    (tmp / "contact.json").write_text(json.dumps(
        {"website": "https://aiagentcycle.com", "scan": "https://aiagentcycle.com/nl/scan/", "internal": "nee"}), encoding="utf-8")
    _doc(tmp, 20, "prijzen", title="Prijzen", body=PRIJZEN)
    _doc(tmp, 1, "audit", title="Audit", body="Een audit in de kennisbank.")
    _doc(tmp, 907, "afas", type="integration", title="AFAS Profit koppelen", body="AFAS koppelen met je webshop en Exact Online.")
    _doc(tmp, 744, "mercabilis", type="case", title="Mercabilis en Exact Online", summary="WooCommerce aan Exact Online", body="Veertien workflows.")
    _doc(tmp, 745, "mercabilis-en", lang="en", type="case", title="Mercabilis and Exact Online", body="Fourteen workflows.")
    _doc(tmp, 3, "pricing", lang="en", title="Pricing", body="Automation with n8n and clear agreements.")
    outside = tmp / "outside.md"
    outside.write_text("# Buiten\n", encoding="utf-8")
    try:
        (tmp / "kb" / "9-link.md").symlink_to(outside)
    except OSError:
        pass


def _env(tmp: Path) -> None:
    import os

    os.environ["AAC_MCP_CONTENT"] = str(tmp)
    os.environ["AAC_MCP_LOG"] = str(tmp / "toolcalls.jsonl")
    os.environ["AAC_MCP_SYNC_LOG"] = str(tmp / "sync-report.txt")


def _call(tmp: Path, name: str, args: dict | None = None):
    _env(tmp)
    from aac_mcp.server import build_mcp

    async def run():
        from fastmcp import Client

        async with Client(build_mcp()) as client:
            return await client.call_tool(name, args or {}, raise_on_error=False)

    return asyncio.run(run())


def _data(result) -> dict:
    assert not result.is_error, _text(result)
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def _text(result) -> str:
    return "\n".join(getattr(block, "text", str(block)) for block in result.content)


def _tools(tmp: Path):
    _env(tmp)
    from aac_mcp.server import build_mcp

    async def run():
        from fastmcp import Client

        async with Client(build_mcp()) as client:
            return await client.list_tools()

    return asyncio.run(run())


CATALOG = {
    "lang": "nl", "source": "https://aiagentcycle.com/nl/koppelingen/", "updated": "2026-11-02", "count": 3,
    "domains": {"administratie": "Geld & administratie", "data": "Data, servers & AI"},
    "items": [
        {"name": "Exact Online", "status": "productie", "open_source": False, "domain": "administratie", "domain_label": "Geld & administratie",
         "category": "Boekhouding en ERP koppelen", "description": "Orders en prijzen synchroniseren.", "url": "https://aiagentcycle.com/nl/exact-online-koppelen-n8n/"},
        {"name": "Twinfield", "status": "maatwerk", "open_source": False, "domain": "administratie", "domain_label": "Geld & administratie",
         "category": "Boekhouding en ERP koppelen", "description": "Boekingen aanleveren via de API."},
        {"name": "Qdrant", "status": "standaard", "open_source": True, "license": "Apache-2.0", "domain": "data", "domain_label": "Data, servers & AI",
         "category": "Vector databases", "description": "Vectoren opslaan voor RAG."},
    ],
}


def test_list_integrations_filters_and_llms(tmp_path: Path):
    _tree(tmp_path)
    (tmp_path / "integrations.nl.json").write_text(json.dumps(CATALOG), encoding="utf-8")
    (tmp_path / "integrations.en.json").write_text(json.dumps({**CATALOG, "lang": "en"}), encoding="utf-8")
    everything = _data(_call(tmp_path, "list_integrations", {"lang": "nl"}))
    assert everything["total_systems"] == 3 and everything["count"] == 3 and "productie" in everything["status_legend"]
    assert [i["name"] for i in _data(_call(tmp_path, "list_integrations", {"query": "twinfield"}))["integrations"]] == ["Twinfield"]
    assert [i["name"] for i in _data(_call(tmp_path, "list_integrations", {"open_source": True}))["integrations"]] == ["Qdrant"]
    assert [i["name"] for i in _data(_call(tmp_path, "list_integrations", {"status": "productie", "domain": "administratie"}))["integrations"]] == ["Exact Online"]
    none = _data(_call(tmp_path, "list_integrations", {"query": "bestaatniet"}))
    assert none["count"] == 0 and "custom work" in none["note"]
    assert _call(tmp_path, "list_integrations", {"domain": "x"}).is_error
    assert _call(tmp_path, "list_integrations", {"status": "x"}).is_error
    _env(tmp_path)
    from starlette.testclient import TestClient

    from aac_mcp.server import create_app

    with TestClient(create_app()) as client:
        llms = client.get("/llms.txt").text
        assert "Integrations: 3 systems" in llms and "- Qdrant (n8n built-in; open source, Apache-2.0): Vectoren opslaan voor RAG." in llms
        assert "### Geld & administratie / Boekhouding en ERP koppelen" in llms
        assert "- Twinfield (maatwerk)" in client.get("/llms-full.txt").text


def test_ten_tools_readonly_with_titles(tmp_path: Path):
    tools = _tools(tmp_path)
    assert [tool.name for tool in tools] == [
        "get_company_profile", "list_services", "get_service", "search_knowledge_base", "get_document",
        "list_documents", "list_integrations", "get_faq", "list_cases", "get_contact_info",
    ]
    for tool in tools:
        assert tool.title
        assert tool.annotations.readOnlyHint is True
        assert tool.outputSchema is not None
        for name, prop in tool.inputSchema.get("properties", {}).items():
            assert len(prop.get("description", "")) > 20, f"{tool.name}.{name} heeft geen beschrijving"
    schema = {t.name: t.inputSchema["properties"] for t in tools}
    assert schema["search_knowledge_base"]["lang"]["enum"] == ["nl", "en"]
    assert "integration" in schema["list_documents"]["type"]["enum"]


def test_icons_in_card_registry_and_served(tmp_path: Path):
    _tree(tmp_path)
    _env(tmp_path)
    from starlette.testclient import TestClient

    from aac_mcp import docs
    from aac_mcp.server import create_app

    assert docs.registry_server_json()["icons"][0]["src"] == "https://mcp.aiagentcycle.com/icon-512.png"
    assert docs.registry_server_json()["repository"] == {"url": "https://github.com/aiagentcycle/aiagentcycle-mcp", "source": "github", "id": "1443482395"}
    with TestClient(create_app()) as client:
        assert client.get("/mcp/server-card").json()["icons"] == docs.ICONS
        png = client.get("/icon-512.png")
        assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content[:4] == b"\x89PNG"
        init = client.post(
            "/mcp", headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        )
        assert "icon-512.png" in init.text


def test_profile_services_contact_strip_internal_and_verify(tmp_path: Path):
    _tree(tmp_path)
    profile = _data(_call(tmp_path, "get_company_profile", {"lang": "nl"}))
    assert profile["facts_verified"] is True and "verify" not in profile and "_draft" not in profile
    listed = _data(_call(tmp_path, "list_services"))
    by_id = {s["id"]: s for s in listed["services"]}
    assert "internal_notes" not in by_id["quick-win"] and "verify" not in by_id["quick-win"]
    assert by_id["quick-win"]["price_verified"] is True
    assert by_id["training"]["price_verified"] is None
    assert listed["all_prices_verified"] is True and "warning" not in listed
    one = _data(_call(tmp_path, "get_service", {"service_id": "techbeheer"}))
    assert one["price_verified"] is True
    missing = _call(tmp_path, "get_service", {"service_id": "bestaat-niet"})
    assert missing.is_error and "unknown service" in _text(missing)
    contact = _data(_call(tmp_path, "get_contact_info"))
    assert contact["scan"].endswith("/nl/scan/") and "internal" not in contact


def test_changed_price_is_flagged(tmp_path: Path):
    _tree(tmp_path)
    _doc(tmp_path, 20, "prijzen", title="Prijzen", body="Quick-win | Vanaf €950\nTechbeheer €250 per maand")
    listed = _data(_call(tmp_path, "list_services"))
    by_id = {s["id"]: s for s in listed["services"]}
    assert by_id["quick-win"]["price_verified"] is False
    assert listed["all_prices_verified"] is False and "get_document(20)" in listed["warning"]


def test_search_ranks_any_word_filters_lang_and_type(tmp_path: Path):
    _tree(tmp_path)
    found = _data(_call(tmp_path, "search_knowledge_base", {"query": "Exact Online koppeling AFAS Moneybird", "lang": "nl"}))
    ids = [hit["id"] for hit in found["hits"]]
    assert ids[0] == 907 and 744 in ids and 745 not in ids
    hit = found["hits"][0]
    assert hit["url"] == "https://aiagentcycle.com/nl/afas/" and hit["type"] == "integration"
    assert "AFAS" in hit["snippet"] and not hit["snippet"].startswith("---")
    cases = _data(_call(tmp_path, "search_knowledge_base", {"query": "Exact Online", "lang": "nl", "type": "case"}))
    assert [h["id"] for h in cases["hits"]] == [744]
    other = _data(_call(tmp_path, "search_knowledge_base", {"query": "agreements", "lang": "nl"}))
    assert other["hits"] == [] and "lang=en" in other["note"]
    assert all(h["id"] != 9 for h in found["hits"])


def test_search_rejects_bad_input_and_logs_hash_only(tmp_path: Path):
    _tree(tmp_path)
    for args, needle in (({"query": "a" * 101}, "100"), ({"query": "x", "lang": "de"}, "lang"),
                         ({"query": "x", "type": "blog"}, "type"), ({"query": "x", "limit": 11}, "limit")):
        result = _call(tmp_path, "search_knowledge_base", args)
        assert result.is_error and needle in _text(result)
    log = (tmp_path / "toolcalls.jsonl").read_text(encoding="utf-8")
    row = json.loads(log.strip().splitlines()[-1])
    for key in ("ts", "tool", "args_sha256", "status", "duration_ms", "bytes", "user_agent", "mcp_name"):
        assert key in row
    assert "a" * 101 not in log
    assert row["args_sha256"] == args_hash({"query": "x", "lang": "nl", "limit": 11, "type": ""})


def test_get_document_list_documents_and_cases(tmp_path: Path):
    _tree(tmp_path)
    doc = _data(_call(tmp_path, "get_document", {"id": 907}))
    assert doc["title"] == "AFAS Profit koppelen" and "Exact Online" in doc["text"] and doc["truncated"] is False
    assert doc["markdown_url"] == "https://mcp.aiagentcycle.com/md/907.md" and not doc["text"].startswith("#")
    missing = _call(tmp_path, "get_document", {"id": 12345})
    assert missing.is_error and "list_documents" in _text(missing)
    listed = _data(_call(tmp_path, "list_documents", {"lang": "nl", "type": "integration"}))
    assert listed["count"] == 1 and listed["documents"][0]["id"] == 907
    everything = _data(_call(tmp_path, "list_documents", {"lang": "nl"}))
    assert {d["id"] for d in everything["documents"]} == {20, 1, 907, 744}
    cases = _data(_call(tmp_path, "list_cases", {"lang": "en"}))
    assert [c["id"] for c in cases["cases"]] == [745]
    faq = _data(_call(tmp_path, "get_faq", {"lang": "nl"}))
    assert faq["items"]


def test_index_follows_kb_swap(tmp_path: Path):
    _tree(tmp_path)
    assert _data(_call(tmp_path, "list_documents", {"lang": "nl"}))["count"] == 4
    new = tmp_path / ".staging"
    new.mkdir()
    (tmp_path / "kb" / "1-audit.md").rename(new / "1-audit.md")
    (tmp_path / "kb").rename(tmp_path / ".prev")
    new.rename(tmp_path / "kb")
    assert _data(_call(tmp_path, "list_documents", {"lang": "nl"}))["count"] == 1


def test_cap_on_and_off():
    big = "x" * (MAX_BYTES + 1000)
    capped = cap_text(big)
    assert "AFGEKAPT" in capped
    assert len(capped.encode("utf-8")) <= MAX_BYTES
    open_limit = cap_text(big, limit=MAX_BYTES + 5000)
    assert "AFGEKAPT" not in open_limit


def test_realpath_skips_outside(tmp_path: Path):
    _tree(tmp_path)
    files = [path.name for path in kb_files(tmp_path)]
    assert "1-audit.md" in files
    assert "9-link.md" not in files


def test_origin_rules():
    assert origin_allowed(None) is True
    assert origin_allowed("") is True
    assert origin_allowed("https://mcp.aiagentcycle.com") is True
    assert origin_allowed("https://evil.example") is False
    assert origin_allowed("https://evil.example", enabled=False) is True


def test_http_routes_discovery_and_origin(tmp_path: Path):
    _tree(tmp_path)
    _env(tmp_path)
    (tmp_path / "sync-report.txt").write_text("total 6\nfinished 2099-01-01T00:00:00Z\n", encoding="utf-8")
    from starlette.testclient import TestClient

    from aac_mcp import __version__
    from aac_mcp.server import create_app

    with TestClient(create_app(), follow_redirects=False) as client:
        assert client.post("/mcp", headers={"Origin": "https://evil.example"}, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}).status_code == 403
        init = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        )
        assert init.status_code == 200 and f'"version":"{__version__}"' in init.text.replace(" ", "")
        card = client.get("/mcp/server-card")
        assert card.status_code == 200 and card.headers["content-type"].startswith("application/mcp-server-card+json")
        assert card.json()["version"] == __version__ and card.json()["remotes"][0]["url"] == "https://mcp.aiagentcycle.com/mcp"
        assert client.get("/mcp/server-card", headers={"If-None-Match": card.headers["etag"]}).status_code == 304
        catalog = client.get("/.well-known/ai-catalog.json")
        assert catalog.json()["entries"][0]["url"].endswith("/mcp/server-card")
        llms = client.get("/llms.txt")
        assert llms.status_code == 200 and "AFAS Profit koppelen" in llms.text and "/md/907.md" in llms.text
        full = client.get("/llms-full.txt")
        assert "Veertien workflows." in full.text and "Fourteen workflows." in full.text
        md = client.get("/md/907.md")
        assert md.status_code == 200 and md.text.startswith("# AFAS Profit koppelen") and "Source: https://aiagentcycle.com/nl/afas/" in md.text
        assert client.get("/md/999.md").status_code == 404 and client.get("/md/..%2Fprofile.nl.json").status_code == 404
        assert client.get("/").status_code == 302
        assert "llms.txt" in client.get("/robots.txt").text
        health = client.get("/healthz").json()
        assert health["status"] == "ok" and health["documents"] == 6 and health["version"] == __version__
