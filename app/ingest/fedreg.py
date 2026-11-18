"""Parse Federal Register rules and proposed rules (XML) into chunks.

Spec: docs/specs/fedreg.md

A document becomes a sequence of units, each split into chunks with split_article:
a summary unit from the preamble, one unit per heading of the supplementary information,
and one unit per regulatory text section (§).
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date

from app.config import settings
from app.ingest.chunker import ChunkData, SourceDocument, split_article

KEEP_SINCE: str = "2010-01-01"
OSHA_MAX_PAGES: int = 5

WHD = "wage-and-hour-division"
OSHA = "occupational-safety-and-health-administration"

KINDS = {"Rule": "Final rule", "Proposed Rule": "Proposed rule"}
CATEGORIES = {
    WHD: "Federal Register: Wage and hour",
    OSHA: "Federal Register: Safety and health",
}

# Elements whose text never reaches a chunk. Their tail text (what follows them inside the
# parent) is kept, so a page marker in the middle of a sentence does not cut it.
DROP = {
    "FTNT", "SU", "FTREF", "PRTPAGE", "STARS", "AMDPAR", "AUTH", "LSTSUB", "SIG", "FRDOC",
    "BILCOD", "AGENCY", "SUBAGY", "CFR", "DEPDOC", "RIN", "AGY", "ADD", "FURINF",
}
LINE_TAGS = {"P", "FP"}
HEADING_SOURCE = re.compile(r"HD(\d+)")
TABLE_OF_CONTENTS = "Preamble Table of Contents"
SUPPLEMENTARY = "Supplementary information"
CHAPTER_MAX = 500  # database column sizes
ARTICLE_NO_MAX = 50


@dataclass
class Unit:
    heading: str
    article_no: str
    chapter: str
    lines: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def qualifies(entry: dict) -> bool:
    if entry["type"] not in KINDS or entry["publication_date"] < KEEP_SINCE:
        return False
    if entry["agency"] == WHD:
        return True
    return entry["agency"] == OSHA and entry["page_length"] <= OSHA_MAX_PAGES


def select_documents(catalog: list[dict]) -> list[dict]:
    seen: set[str] = set()
    selected: list[dict] = []
    for entry in catalog:
        number = entry["document_number"]
        if number not in seen and qualifies(entry):
            seen.add(number)
            selected.append(entry)
    return selected


# ---------------------------------------------------------------------------
# Text and lines
# ---------------------------------------------------------------------------


def clean(text: str) -> str:
    """Collapse every run of (Unicode) whitespace, thin spaces included, to one space."""
    return " ".join(text.split())


def raw_text(el: ET.Element) -> str:
    parts = [el.text or ""]
    for child in el:
        if child.tag not in DROP:
            parts.append(raw_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def text(el: ET.Element | None) -> str:
    return "" if el is None else clean(raw_text(el))


def table_lines(table: ET.Element) -> list[str]:
    lines = [text(table.find("TTITLE"))]
    lines.append(" | ".join(text(ched) for ched in table.iter("CHED")))
    lines += [" | ".join(text(ent) for ent in row.iter("ENT")) for row in table.iter("ROW")]
    return [line for line in lines if line.strip(" |")]


def block_lines(el: ET.Element) -> list[str]:
    """The lines of one element: a paragraph is one line, a table one line per row."""
    if el.tag in DROP or el.tag == "HD":
        return []
    if el.tag in LINE_TAGS:
        line = text(el)
        return [line] if line else []
    if el.tag == "GPOTABLE":
        return table_lines(el)
    # EXTRACT, NOTE and other wrappers: read through for the lines inside.
    return [line for child in el for line in block_lines(child)]


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


def summary_unit(preamble: ET.Element, subject: str) -> Unit:
    unit = Unit(subject, "Summary", subject)
    for tag, label in (("ACT", "Action"), ("SUM", "Summary"), ("EFFDATE", "Dates")):
        el = preamble.find(tag)
        if el is not None:
            body = " ".join(line for child in el for line in block_lines(child))
            if body:
                unit.lines.append(f"{label}: {body}")
    return unit


def section_units(regtext: ET.Element, subject: str) -> list[Unit]:
    chapter = (
        f"{subject} > Regulatory text > "
        f"{regtext.get('TITLE', '')} CFR Part {regtext.get('PART', '')}"
    )
    units = []
    for section in regtext.iter("SECTION"):
        number = text(section.find("SECTNO"))
        heading = clean(f"{number} {text(section.find('SUBJECT'))}")
        lines = [
            line
            for child in section
            if child.tag not in {"SECTNO", "SUBJECT"}
            for line in block_lines(child)
        ]
        units.append(Unit(heading, number, chapter, lines))
    return units


def body_units(root: ET.Element, subject: str) -> list[Unit]:
    """Preamble heading units and regulatory text units, in document order.

    A heading unit is added when its heading is met, and the lines that follow are added
    to it, so a unit keeps the position of its heading even when regulatory text comes
    before its next line.
    """
    units: list[Unit] = []
    current = Unit(SUPPLEMENTARY, SUPPLEMENTARY, f"{subject} > {SUPPLEMENTARY}")
    units.append(current)
    path: list[tuple[int, str]] = []  # enclosing headings as (level, text)
    skipping = False  # inside the preamble table of contents

    elements = []
    for child in root:
        elements += list(child) if child.tag == "SUPLINF" else [child]

    for el in elements:
        if el.tag == "REGTEXT":
            units += section_units(el, subject)
            continue
        match = HEADING_SOURCE.fullmatch(el.get("SOURCE", "")) if el.tag == "HD" else None
        if match:
            level, heading = int(match.group(1)), text(el)
            if level == 1:
                skipping = heading == TABLE_OF_CONTENTS
            if skipping:
                current = None
                continue
            path = [(lvl, hd) for lvl, hd in path if lvl < level] + [(level, heading)]
            article_no = path[0][1] if path[0][0] == 1 else heading
            chapter = " > ".join([subject, *(hd for _, hd in path)])
            current = Unit(heading, article_no, chapter)
            units.append(current)
        elif current is not None and el.tag not in {"PREAMB", "SECTION"}:
            current.lines += block_lines(el)

    return [unit for unit in units if unit.lines]


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def parse_document(xml: bytes, entry: dict, max_chars: int = settings.chunk_size) -> SourceDocument:
    root = ET.fromstring(xml)
    if root.tag not in {"RULE", "PRORULE"}:
        raise ValueError(f"not a rule or proposed rule: <{root.tag}>")
    preamble = root.find("PREAMB")
    subject = text(preamble.find("SUBJECT")) if preamble is not None else ""
    if not subject:
        raise ValueError("the preamble has no SUBJECT")

    units = [summary_unit(preamble, subject), *body_units(root, subject)]
    chunks: list[ChunkData] = []
    for unit in units:
        # Cut to the database column sizes; the content keeps the full heading and lines.
        chapter = unit.chapter[:CHAPTER_MAX]
        article_no = unit.article_no[:ARTICLE_NO_MAX]
        for piece in split_article("\n".join([unit.heading, *unit.lines]), max_chars):
            chunks.append(ChunkData(len(chunks), chapter, article_no, piece))

    number, published = entry["document_number"], entry["publication_date"]
    return SourceDocument(
        title=f"FR Doc. {number} ({KINDS[entry['type']]}, {published})",
        category=CATEGORIES[entry["agency"]],
        source_url=entry["html_url"],
        modified_date=date.fromisoformat(published),
        chunks=chunks,
    )
