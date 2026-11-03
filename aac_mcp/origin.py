"""Origin guard for /mcp. A missing Origin is allowed. Any other value must be on the list.

Pure ASGI middleware so Streamable HTTP keeps its response stream. Mount it with
``starlette.middleware.Middleware`` inside ``FastMCP.http_app`` so the FastMCP
lifespan stays on the outer application.
"""

from __future__ import annotations

ALLOWED_ORIGINS = frozenset(
    {
        "https://mcp.aiagentcycle.com",
        "http://127.0.0.1:8321",
        "http://localhost:8321",
    }
)


def origin_allowed(origin: str | None, *, enabled: bool = True) -> bool:
    if not enabled or origin is None or origin == "":
        return True
    return origin in ALLOWED_ORIGINS


class OriginGuard:
    def __init__(self, app, enabled: bool = True):
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope, receive, send):
        # Alleen het MCP-eindpunt zelf. Server Card, llms.txt, /md/ en iconen zijn openbaar (CORS *).
        if scope.get("type") != "http" or scope.get("path") != "/mcp":
            await self.app(scope, receive, send)
            return
        origin = None
        for key, value in scope.get("headers") or []:
            if key.lower() == b"origin":
                origin = value.decode("latin1")
                break
        if not origin_allowed(origin, enabled=self.enabled):
            body = b"origin rejected"
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"text/plain; charset=utf-8"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
