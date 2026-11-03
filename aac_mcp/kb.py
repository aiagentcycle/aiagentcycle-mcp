"""Index over kb/*.md: metadata uit de YAML-kop, volledige tekst en een BM25-zoekindex.

De sync vervangt kb/ in zijn geheel (rename). Het index wordt opnieuw opgebouwd zodra
inode of mtime van kb/ verandert, dus nooit een half bijgewerkte stand.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

from aac_mcp.content import kb_files
from aac_mcp.search import Bm25, fold, tokens

TYPES = ("article", "page", "integration", "case", "solution", "sector")


@dataclass(frozen=True)
class Doc:
    id: int
    file: str
    slug: str
    type: str
    lang: str
    title: str
    summary: str
    link: str
    modified: str
    text: str

    def meta(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "lang": self.lang,
            "title": self.title,
            "url": self.link,
            "modified": self.modified,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class Index:
    key: tuple
    docs: dict[int, Doc]
    bm25: Bm25

    def by_lang(self, lang: str | None = None, type_: str | None = None) -> list[Doc]:
        found = [d for d in self.docs.values() if (lang is None or d.lang == lang) and (type_ is None or d.type == type_)]
        return sorted(found, key=lambda d: (TYPES.index(d.type) if d.type in TYPES else 99, d.title.casefold()))

    def newest(self) -> str:
        return max((d.modified for d in self.docs.values()), default="")


def front_matter(raw: str) -> tuple[dict, str]:
    """Splitst de YAML-kop die de sync boven elk kb-bestand zet van de tekst."""
    meta: dict = {}
    if raw.startswith("---\n"):
        end = raw.find("\n---", 4)
        if end != -1:
            for line in raw[4:end].splitlines():
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
            raw = raw[end + 4 :].lstrip("\n")
    return meta, raw


def parse(path: Path) -> Doc | None:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    meta, body = front_matter(raw)
    title = meta.get("title", "")
    if body.startswith("# "):
        first, _, rest = body.partition("\n")
        title = title or first[2:].strip()
        body = rest.strip()
    try:
        doc_id = int(meta.get("id") or path.stem.split("-", 1)[0])
    except ValueError:
        return None
    return Doc(
        id=doc_id,
        file=path.name,
        slug=meta.get("slug", path.stem),
        type=meta.get("type", "page"),
        lang=meta.get("lang", "nl"),
        title=title or path.stem,
        summary=meta.get("summary") or " ".join(body[:300].split()),
        link=meta.get("link", ""),
        modified=meta.get("modified", ""),
        text=body,
    )


_lock = threading.Lock()
_cache: Index | None = None


def _key(root: Path) -> tuple:
    kb = root / "kb"
    try:
        stat = kb.stat()
    except OSError:
        return (str(root), None, None)
    return (str(root), stat.st_ino, stat.st_mtime_ns)


def load(root: Path) -> Index:
    global _cache
    key = _key(root)
    cached = _cache
    if cached is not None and cached.key == key:
        return cached
    with _lock:
        if _cache is not None and _cache.key == key:
            return _cache
        docs: dict[int, Doc] = {}
        for path in kb_files(root):
            doc = parse(path)
            if doc is not None:
                docs[doc.id] = doc
        # Titel en samenvatting tellen extra mee in de ranking.
        bm25 = Bm25([(str(d.id), f"{d.title} {d.title} {d.title} {d.summary} {d.text}") for d in docs.values()])
        _cache = Index(key=key, docs=docs, bm25=bm25)
        return _cache


def snippet(doc: Doc, query: str, size: int = 320) -> str:
    """Tekstfragment rond de eerste treffer, zodat een agent ziet waarom dit document matcht."""
    text = " ".join(doc.text.split())
    folded = fold(text)
    starts = [m.start() for t in tokens(query) if (m := re.search(r"\b" + re.escape(t), folded))]
    start = max(0, min(starts) - 80) if starts else 0
    piece = text[start : start + size].strip()
    return ("…" if start else "") + piece + ("…" if start + size < len(text) else "")
