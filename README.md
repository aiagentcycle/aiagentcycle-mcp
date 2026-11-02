# AIAgentCycle MCP server

Read-only [Model Context Protocol](https://modelcontextprotocol.io) server for [aiagentcycle.com](https://aiagentcycle.com), a Dutch company that builds workflow automation, system integrations and AI agents on self-hosted n8n for small and medium-sized businesses.

AI agents can use it to answer questions about the company with up-to-date, sourced facts: services and prices, the 190 systems it integrates, case studies, the knowledge base and contact details. Content is mirrored from the website every hour, in Dutch (primary) and English.

- **Endpoint:** `https://mcp.aiagentcycle.com/mcp` (Streamable HTTP, no login, read-only)
- **MCP Registry:** `com.aiagentcycle/aiagentcycle`
- **Server Card:** <https://mcp.aiagentcycle.com/mcp/server-card>
- **For crawlers and LLMs:** [`llms.txt`](https://mcp.aiagentcycle.com/llms.txt), [`llms-full.txt`](https://mcp.aiagentcycle.com/llms-full.txt), Markdown per page at `/md/{id}.md`

## Connect

Add it as a remote MCP server in any client that supports Streamable HTTP, for example in Claude Code:

```bash
claude mcp add --transport http aiagentcycle https://mcp.aiagentcycle.com/mcp
```

## Tools

| Tool | What it returns |
| --- | --- |
| `search_knowledge_base` | Ranked full-text search over every page, article, case, solution, sector and integration page |
| `get_document` | Full Markdown text of one page, with source URL and last-modified date |
| `list_documents` | Catalogue of the website by language and type |
| `list_integrations` | The 190 systems AIAgentCycle connects, with status (in production, n8n built-in, custom), domain, category and open-source license |
| `list_services` / `get_service` | Services and maintenance packages with indicative prices; each price is checked against the live pricing page (`price_verified`) |
| `list_cases` | Published case studies |
| `get_faq` | FAQ, verbatim from the pricing page |
| `get_company_profile` | Who the company is; key facts checked against the About page (`facts_verified`) |
| `get_contact_info` | Email, phone and the free assessment page. The server never sends messages or books appointments |

All tools are annotated `readOnlyHint: true`, return structured JSON, and log only a hash of their arguments.

## How it stays correct

- `sync/aac_mcp_sync.py` pulls all public content from the WordPress REST API every hour. It also reads the integration catalogue from the published HTML and the FAQ from the FAQPage JSON-LD. The sync is fail-closed: a partial or broken site never replaces the previous knowledge base.
- Hand-maintained facts (prices, profile) carry `verify` strings that must appear verbatim on the live source page. If the site changes, the tools report `price_verified: false` and a daily check turns red.
- A daily check covers reachability, freshness, discovery files, transport rules, TLS and the Registry entry.

## Run locally

```bash
python -m venv .venv && .venv/bin/pip install --require-hashes -r requirements.txt
AAC_MCP_CONTENT=./content python -m aac_mcp --host 127.0.0.1 --port 8321
.venv/bin/python -m pytest -q
```

The server only binds to localhost. In production it runs behind nginx with rate limiting and an Origin check. See `deploy/` for the systemd units and the nginx config. `SCHEMA.md` describes the content files.

Built with [FastMCP](https://github.com/jlowin/fastmcp). Maintained by AIAgentCycle (Good Nature Vibe B.V., Oosterwolde, the Netherlands).

## License

MIT, see `LICENSE`. The texts in `content-published/` are AIAgentCycle's own business information; they are included as an example of the content format.
