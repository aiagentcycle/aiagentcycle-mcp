"""Bind only the host and port given on the command line. Default is localhost."""

from __future__ import annotations

import argparse
import os

import uvicorn

from aac_mcp.server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="AAC read-only MCP server")
    parser.add_argument("--host", default=os.environ.get("AAC_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AAC_MCP_PORT", "8321")))
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("alleen 127.0.0.1 is toegestaan")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
