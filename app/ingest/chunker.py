"""Shared chunk types, and the paragraph-preserving splitter every source uses."""

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ChunkData:
    chunk_index: int
    chapter: str | None
    article_no: str
    content: str


@dataclass(frozen=True)
class SourceDocument:
    """One document from any source, ready to embed and store."""

    title: str
    category: str
    source_url: str
    modified_date: date | None
    chunks: list[ChunkData]


def split_article(content: str, max_chars: int) -> list[str]:
    """Split on line breaks only, repeating the first line (the heading) in every piece."""
    lines = [line.strip() for line in re.split(r"\r?\n", content) if line.strip()]
    whole = "\n".join(lines)
    if len(whole) <= max_chars:
        return [whole]

    lead, rest = lines[0], lines[1:]
    parts: list[str] = []
    current = [lead]
    for line in rest:
        if len(current) > 1 and len("\n".join(current + [line])) > max_chars:
            parts.append("\n".join(current))
            current = [lead]
        current.append(line)
    parts.append("\n".join(current))
    return parts
