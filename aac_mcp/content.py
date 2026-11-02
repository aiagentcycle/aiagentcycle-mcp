"""Read-only content helpers. No paths or URLs from tool arguments."""

from __future__ import annotations

import json
from pathlib import Path

MAX_BYTES = 50 * 1024
TRUNC_MARKER = "\n[AFGEKAPT: resultaat groter dan 51200 bytes]"
INTERNAL_KEYS = {"internal", "internal_notes", "cost", "margin", "owner_only"}


def cap_text(text: str, *, limit: int = MAX_BYTES) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    marker = TRUNC_MARKER.encode("utf-8")
    budget = max(0, limit - len(marker))
    cut = raw[:budget].decode("utf-8", errors="ignore")
    return cut + TRUNC_MARKER


def load_json(root: Path, name: str) -> dict:
    path = (root / name).resolve()
    root_real = root.resolve()
    if not path.is_relative_to(root_real) or not path.is_file():
        raise FileNotFoundError(name)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(name)
    return data


def public_obj(obj: dict) -> dict:
    return {k: v for k, v in obj.items() if k not in INTERNAL_KEYS and not str(k).startswith("_")}


def services(root: Path) -> list[dict]:
    data = load_json(root, "services.json")
    items = data.get("services", [])
    if not isinstance(items, list):
        raise ValueError("services")
    return [public_obj(item) for item in items if isinstance(item, dict)]


def kb_files(root: Path) -> list[Path]:
    kb = (root / "kb").resolve()
    if not kb.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(kb.glob("*.md")):
        try:
            real = path.resolve(strict=True)
        except OSError:
            continue
        if real.is_file() and real.is_relative_to(kb):
            found.append(real)
    return found
