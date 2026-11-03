"""One JSONL line per tool call. Arguments only as a hash."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_USER_AGENT = 120


def args_hash(args: dict) -> str:
    raw = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_call(
    path: Path,
    *,
    tool: str,
    args: dict,
    status: str,
    duration_ms: int,
    nbytes: int,
    user_agent: str,
    mcp_name: str,
) -> None:
    row = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": tool,
        "args_sha256": args_hash(args),
        "status": status,
        "duration_ms": duration_ms,
        "bytes": nbytes,
        "user_agent": user_agent[:MAX_USER_AGENT],
        "mcp_name": mcp_name,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        # Een vol of onleesbaar logpad mag de toolcall zelf niet breken.
        print(f"toolcall log failed: {exc.__class__.__name__}", file=sys.stderr)
