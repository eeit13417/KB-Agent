"""Parse one eCFR part (XML from scripts/fetch_ecfr.py) into section-level chunks.

Each section (§) or appendix becomes one chunk, tagged with its subpart and subject
group so answers can cite e.g. "§ 785.11". Long sections are split by paragraph.
"""

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass

from app.config import settings
from app.ingest.chunker import ChunkData, split_article

HEADING_DIVS = {"DIV6", "DIV7"}  # subpart, subject group
SECTION_DIVS = {"DIV8", "DIV9"}  # section, appendix
CONTAINERS = {"DIV", "EXTRACT", "NOTE", "EXAMPLE"}
# Source notes such as "[35 FR 15289, Oct. 1, 1970]": provenance, not something to answer from.
SKIP = {"HEAD", "CITA", "SECAUTH"}
SMALL_WORDS = {"a", "and", "as", "by", "for", "from", "in", "of", "on", "or", "the", "to", "under"}


@dataclass(frozen=True)
class CfrPart:
    number: str
    name: str
    chunks: list[ChunkData]


def clean(text: str) -> str:
    return " ".join(text.split())


def heading(el: ET.Element) -> str:
    return clean(el.findtext("HEAD") or "")


def title_case(text: str) -> str:
    """'HOURS WORKED' -> 'Hours Worked'. Part names arrive in all caps."""
    words = text.title().split()
    return " ".join(w.lower() if i and w.lower() in SMALL_WORDS else w for i, w in enumerate(words))


def block_lines(el: ET.Element) -> list[str]:
    """One line per paragraph and per table row, so a split never cuts a paragraph in half."""
    if el.tag in SKIP:
        return []
    if el.tag == "TABLE":
        rows = (" | ".join(clean("".join(cell.itertext())) for cell in tr) for tr in el.iter("TR"))
        return [row for row in rows if row.strip(" |")]
    if el.tag in CONTAINERS:
        return [line for child in el for line in block_lines(child)]
    text = clean("".join(el.itertext()))
    return [text] if text else []


def section_number(el: ET.Element) -> str:
    # Sections carry "785.11"; appendices carry a name such as "Appendix A to Part 801".
    number = el.get("N", "")
    return f"§ {number}" if el.tag == "DIV8" else number


def walk(el: ET.Element, path: list[str]) -> Iterator[tuple[str | None, ET.Element]]:
    for child in el:
        if child.tag in HEADING_DIVS:
            yield from walk(child, [*path, heading(child)])
        elif child.tag in SECTION_DIVS:
            yield " / ".join(path) or None, child


def chunk_part(xml: bytes, max_chars: int = settings.chunk_size) -> CfrPart:
    root = ET.fromstring(xml)
    # "PART 785—HOURS WORKED" -> "Hours Worked"
    name = title_case(heading(root).partition("\u2014")[2])

    chunks: list[ChunkData] = []
    for chapter, section in walk(root, []):
        head = heading(section)
        lines = [line for child in section for line in block_lines(child)]
        if "[Reserved]" in head or not lines:
            continue
        for piece in split_article("\n".join([head, *lines]), max_chars):
            chunks.append(ChunkData(len(chunks), chapter, section_number(section), piece))

    return CfrPart(root.get("N", ""), name, chunks)
