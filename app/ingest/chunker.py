"""Split a law (from the MOJ law API JSON) into article-level chunks for embedding.

Each article becomes one chunk, tagged with its chapter path and article number
so answers can cite e.g. "勞動基準法 第 38 條".
"""

import re
from dataclasses import dataclass

from app.config import settings

HEADING_LEVELS = {"章": 0, "節": 1, "款": 2}
HEADING_RE = re.compile(r"第\s*\S+?\s*([章節款])")
DELETED_MARKERS = {"（刪除）", "(刪除)"}


@dataclass(frozen=True)
class ChunkData:
    chunk_index: int
    chapter: str | None
    article_no: str
    content: str


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_article(content: str, max_chars: int) -> list[str]:
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


def chunk_law(law: dict, max_chars: int = settings.chunk_size) -> list[ChunkData]:
    headings: list[str] = []
    chunks: list[ChunkData] = []

    for article in law["LawArticles"]:
        text = article["ArticleContent"]

        if article["ArticleType"] == "C":
            heading = normalize(text)
            match = HEADING_RE.match(heading)
            level = HEADING_LEVELS[match.group(1)] if match else 0
            headings = headings[:level] + [heading]
            continue

        if text.strip() in DELETED_MARKERS:
            continue

        chapter = " / ".join(headings) or None
        for part in split_article(text, max_chars):
            chunks.append(ChunkData(len(chunks), chapter, normalize(article["ArticleNo"]), part))

    return chunks
