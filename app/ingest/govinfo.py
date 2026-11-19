"""Parse govinfo PDFs: annual CFR part editions and Statutes at Large scans.

Spec: docs/specs/govinfo.md

Both parsers read the PDF's own text layer with PyMuPDF and work from layout, not from
markup: a CFR edition is a born-digital two-column page whose structure shows in its fonts
(bold section headings, small-capitals group headings, AvantGarde part and subpart
headings); a Statutes at Large volume is a page scan whose OCR layer has one text column
with marginal notes beside it.
"""

import re
from dataclasses import dataclass, field
from datetime import date

import pymupdf

from app.config import settings
from app.ingest.chunker import ChunkData, SourceDocument, split_article
from app.ingest.ecfr import title_case

CHAPTER_MAX = 500  # database column sizes
ARTICLE_NO_MAX = 50

EM_DASH = "—"
EN_DASH = "–"

# GPO CFR pages are 612 x 792 points with the two text columns inside this box. Running
# heads sit above it, page numbers and GPO production lines below or beside it.
CFR_BODY = pymupdf.Rect(110, 172, 505, 714)

APPENDIX_HEADING = re.compile(r"(NON-MANDATORY |MANDATORY )?APPENDIX\b")
SOURCE_NOTE = re.compile(r"\[.*\bFR\b.*\]")
DOT_LEADER = re.compile(r"\.{3,}")
# Newer CFR editions put a space after a hyphen that is part of the word ("clothes- ").
HARD_HYPHEN_RAW = re.compile(r"[A-Za-z]-\s+$")
HARD_HYPHEN_END = re.compile(r"[A-Za-z]- $")


@dataclass
class Unit:
    heading: str
    article_no: str
    chapter: str
    lines: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def clean(text: str) -> str:
    """Collapse whitespace and turn GPO's doubled single quotes into double quotes."""
    text = text.replace("‘‘", "“").replace("’’", "”")
    return " ".join(text.split())


def join_lines(first: str, second: str) -> str:
    """Join two printed lines, mending a word broken by a hyphen at the line end.

    A CFR row whose hyphen was followed by a space in the text layer keeps that one
    trailing space (see `page_rows`): the hyphen belongs to the word and stays.
    """
    if not first or not second:
        return first or second
    if HARD_HYPHEN_END.search(first):
        return first[:-1] + second  # clothes- + changing -> clothes-changing
    if len(first) >= 2 and first[-1] == "-" and first[-2].isalpha():
        before, after = first[-2], second[0]
        if after.isalpha() and before.isupper() == after.isupper():
            return first[:-1] + second  # com- + putation -> computation
        return first + second  # Portal-to- + Portal Act -> Portal-to-Portal Act
    if first[-1] in (EN_DASH, EM_DASH):
        return first + second
    return f"{first} {second}"


def join_all(lines: list[str]) -> str:
    text = ""
    for line in lines:
        text = join_lines(text, line)
    return text.rstrip()


# ---------------------------------------------------------------------------
# Units to chunks
# ---------------------------------------------------------------------------


def to_chunks(units: list[Unit], max_chars: int) -> list[ChunkData]:
    chunks: list[ChunkData] = []
    for unit in units:
        if not unit.lines:
            continue
        chapter = unit.chapter[:CHAPTER_MAX]
        article_no = unit.article_no[:ARTICLE_NO_MAX]
        for piece in split_article("\n".join([unit.heading, *unit.lines]), max_chars):
            chunks.append(ChunkData(len(chunks), chapter, article_no, piece))
    return chunks


# ---------------------------------------------------------------------------
# CFR parts: rows
# ---------------------------------------------------------------------------


@dataclass
class Row:
    """One printed line of one column, with what its fonts say about it."""

    text: str
    x0: float
    indent: float  # distance from the column's left edge
    size: float  # largest font size in the row
    kind: str  # "heading", "bold", "caps", "table" or "text"


def row_kind(spans: list[dict]) -> str:
    fonts = [s["font"] for s in spans]
    if all("AvantGarde" in f for f in fonts):
        return "heading"  # part and subpart headings
    if any("Helvetica" in f or "Arial" in f for f in fonts):
        return "table"  # GPO sets tables in a sans-serif face
    if all("Bold" in f for f in fonts):
        return "bold"  # section headings
    if is_small_caps(spans):
        return "caps"
    return "text"


def is_small_caps(spans: list[dict]) -> bool:
    """Small capitals: capitals in two sizes, with (almost) no lowercase letters.

    Group and appendix headings are set this way. So are the labels of notes such as
    "EFFECTIVE DATE NOTE: ...", but those rows go on in lowercase or carry a colon.
    """
    sizes = sorted({round(s["size"], 1) for s in spans})
    if len(sizes) < 2:
        return False
    small = "".join(s["text"] for s in spans if round(s["size"], 1) == sizes[0])
    if not any(c.isalpha() for c in small) or any(c.islower() for c in small):
        return False
    text = "".join(s["text"] for s in spans)
    letters = [c for c in text if c.isalpha()]
    lowercase = sum(c.islower() for c in letters)
    return ":" not in text and lowercase <= 0.15 * len(letters)


def spanning_table(page: pymupdf.Page, middle: float) -> tuple[float, float] | None:
    """The y-range of a table spanning both columns, from the rules drawn across it.

    GPO rules such a table with horizontal lines that cross the column gap; tables inside
    one column have rules no wider than the column.
    """
    ys = [
        d["rect"].y0
        for d in page.get_drawings()
        if d["rect"].height < 2
        and d["rect"].x0 < middle - 20 < middle + 20 < d["rect"].x1
        and CFR_BODY.y0 <= d["rect"].y0 <= CFR_BODY.y1
    ]
    return (min(ys), max(ys)) if ys else None


def page_rows(page: pymupdf.Page) -> list[Row]:
    """The rows of one page, read column by column.

    The left column top to bottom, then the right column. A table spanning both columns
    splits the page into three bands, each read column by column: the text above it, the
    table, the text below it.
    """
    middle = page.rect.width / 2
    lines: list[dict] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            # Spaces often come as spans of their own: keep them for the text, but judge
            # fonts and sizes by the visible spans only.
            visible = [s for s in line["spans"] if s["text"].strip()]
            if visible and pymupdf.Rect(line["bbox"]) in CFR_BODY:
                lines.append({"bbox": line["bbox"], "spans": line["spans"], "visible": visible})
    if not lines:
        return []

    def column(line: dict) -> int:
        return 0 if line["bbox"][0] < middle else 1

    # Indents are measured from each column's left edge on the whole page.
    lefts = {
        c: min((ln["bbox"][0] for ln in lines if column(ln) == c), default=0.0) for c in (0, 1)
    }
    table = spanning_table(page, middle)

    def band(line: dict) -> int:
        if table is None:
            return 0
        y = line["bbox"][1]
        return 0 if y < table[0] else 1 if y <= table[1] else 2

    rows: list[Row] = []
    for b in range(3):
        for c in (0, 1):
            part = [ln for ln in lines if band(ln) == b and column(ln) == c]
            rows.extend(column_rows(part, lefts[c]))
    return rows


def column_rows(lines: list[dict], left: float) -> list[Row]:
    """The rows of one column (or of one band of it), top to bottom."""
    rows: list[Row] = []
    if lines:
        lines.sort(key=lambda line: (line["bbox"][1], line["bbox"][0]))
        groups: list[list[dict]] = []
        for line in lines:
            # Justified text and table cells come as several PDF lines on one baseline.
            if groups and abs(line["bbox"][1] - groups[-1][0]["bbox"][1]) < 2:
                groups[-1].append(line)
            else:
                groups.append([line])
        for group in groups:
            group.sort(key=lambda line: line["bbox"][0])
            spans = [s for line in group for s in line["visible"]]
            kind = row_kind(spans)
            cells = [clean("".join(s["text"] for s in line["spans"])) for line in group]
            if kind == "table":
                cells = [c for c in (DOT_LEADER.sub("", cell).strip() for cell in cells) if c]
                text = " | ".join(cells)
            else:
                text = clean(" ".join(cells))
                raw = "".join(s["text"] for s in group[-1]["spans"])
                if text and HARD_HYPHEN_RAW.search(raw):
                    text += " "  # marks a hyphen that belongs to the word, for join_lines
            if text:
                x0 = group[0]["bbox"][0]
                size = max(round(s["size"], 1) for s in spans)
                rows.append(Row(text, x0, x0 - left, size, kind))
    return rows


# ---------------------------------------------------------------------------
# CFR parts: structure
# ---------------------------------------------------------------------------


def is_part_heading(row: Row, part: str | None = None) -> bool:
    number = re.escape(part) if part else r"[\w.-]+"
    return (
        row.kind == "heading"
        and row.size >= 9.5
        and re.match(rf"PART {number}\s*{EM_DASH}", row.text, re.IGNORECASE) is not None
    )


def is_subpart_heading(row: Row) -> bool:
    return row.kind == "heading" and row.size >= 9.5 and row.text.startswith("Subpart")


def is_section_heading(row: Row) -> bool:
    return row.kind == "bold" and row.text.startswith("§")


def take_heading(rows: list[Row], i: int, same) -> tuple[str, int]:
    """Join the heading starting at rows[i] with the rows that continue it."""
    lines = [rows[i].text]
    i += 1
    while i < len(rows) and same(rows[i]):
        lines.append(rows[i].text)
        i += 1
    return join_all(lines), i


def part_bounds(rows: list[Row], part: str) -> tuple[str, int, int]:
    """The part name and the row range of the part's body, front matter skipped."""
    start = next((i for i, row in enumerate(rows) if is_part_heading(row, part)), None)
    if start is None:
        raise ValueError(f"no PART {part}{EM_DASH} heading in the PDF")
    size = rows[start].size
    heading, i = take_heading(
        rows,
        start,
        lambda r: r.kind == "heading"
        and r.size == size
        and not is_part_heading(r)
        and not r.text.startswith("Subpart"),
    )
    name = title_case(heading.partition(EM_DASH)[2])

    end = next((j for j in range(i, len(rows)) if is_part_heading(rows[j])), len(rows))
    # The table of contents and its notes run up to the first subpart or section heading.
    body = next(
        (j for j in range(i, end) if is_subpart_heading(rows[j]) or is_section_heading(rows[j])),
        end,
    )
    return name, body, end


def appendix_heading(text: str) -> str:
    """Title-case an appendix heading, keeping the letter or number that names it."""
    printed = text.split()
    words = title_case(text).split()
    for i, word in enumerate(printed[:-1]):
        # "APPENDIX A TO ..." keeps "A"; "APPENDIX TO PART 541" has no designator.
        if word == "APPENDIX" and re.fullmatch(r"[A-Z]|\d+", printed[i + 1]):
            words[i + 1] = printed[i + 1]
            break
    return " ".join(words)


def section_number(heading: str) -> str:
    match = re.match(r"§\s*(\S+)", heading)
    return match.group(1).rstrip(".") if match else ""


def cfr_units(rows: list[Row], name: str) -> list[Unit]:
    units: list[Unit] = []
    unit: Unit | None = None  # None between units and after a [Reserved] section
    subpart = group = ""
    paragraph: list[str] = []
    paragraph_size = 0.0

    def close_paragraph() -> None:
        nonlocal paragraph
        text = join_all(paragraph)
        paragraph = []
        if unit is not None and text and not SOURCE_NOTE.fullmatch(text):
            unit.lines.append(text)

    i = 0
    while i < len(rows):
        row = rows[i]
        if is_subpart_heading(row):
            close_paragraph()
            subpart, i = take_heading(
                rows, i, lambda r: r.kind == "heading" and not is_subpart_heading(r)
            )
            group, unit = "", None
            continue
        if row.kind == "caps":
            close_paragraph()
            text, i = take_heading(rows, i, lambda r: r.kind == "caps")
            if APPENDIX_HEADING.match(text):
                heading = appendix_heading(text)
                chapter = " / ".join(p for p in (name, subpart) if p)
                unit = Unit(heading, heading.partition(EM_DASH)[0].strip(), chapter)
                units.append(unit)
            else:
                group, unit = title_case(text), None
            continue
        if is_section_heading(row):
            close_paragraph()
            heading, i = take_heading(
                rows, i, lambda r: r.kind == "bold" and not is_section_heading(r)
            )
            number = section_number(heading)
            if unit is not None and unit.article_no == f"§ {number}":
                # A postponed version of the same section, printed after its note.
                unit.lines.append(heading)
            elif "[Reserved]" in heading:
                unit = None
            else:
                chapter = " / ".join(p for p in (name, subpart, group) if p)
                unit = Unit(heading, f"§ {number}", chapter)
                units.append(unit)
            continue
        if row.kind == "table":
            close_paragraph()
            if unit is not None:
                unit.lines.append(row.text)
        else:
            # A paragraph starts with a first-line indent or a change of type size, and
            # otherwise continues, also into the next column or onto the next page.
            if not paragraph or row.indent >= 4 or row.size != paragraph_size:
                close_paragraph()
                paragraph_size = row.size
            paragraph.append(row.text)
        i += 1
    close_paragraph()
    return units


def parse_cfr_part(pdf: bytes, entry: dict, max_chars: int = settings.chunk_size) -> SourceDocument:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        rows = [row for page in doc for row in page_rows(page)]
    name, body, end = part_bounds(rows, entry["part"])
    units = cfr_units(rows[body:end], name)
    year = entry["year"]
    return SourceDocument(
        title=f"29 CFR Part {entry['part']} ({year} edition)",
        category=entry["category"],
        source_url=entry["source_url"],
        modified_date=date(year, 7, 1),
        chunks=to_chunks(units, max_chars),
    )


# ---------------------------------------------------------------------------
# Statutes at Large
# ---------------------------------------------------------------------------


def text_column(words: list[tuple]) -> tuple[float, float]:
    """The x-range of the main text column.

    Word boxes of the text column overlap from line to line into one run along the x axis;
    marginal notes form separate runs beside it, with a gap no text word crosses.
    """
    runs: list[list[float]] = []  # [x0, x1, word count]
    for x0, x1 in sorted((w[0], w[2]) for w in words if re.search(r"[A-Za-z0-9]", w[4])):
        if runs and x0 <= runs[-1][1]:
            runs[-1][1] = max(runs[-1][1], x1)
            runs[-1][2] += 1
        else:
            runs.append([x0, x1, 1])
    if not runs:
        return 0.0, 0.0
    x0, x1, _ = max(runs, key=lambda run: run[2])
    return x0, x1


def statute_page_lines(page: pymupdf.Page) -> list[str]:
    """The text lines of one scanned page, without running head or marginal notes."""
    words = page.get_text("words")  # (x0, y0, x1, y1, text, block, line, word)
    if not words:
        return []
    # The running head is the top line: PUBLIC LAW ...—date, the STAT. locator, a page number.
    # Scan specks without a letter or digit may sit above it, so they do not count.
    readable = [w for w in words if re.search(r"[A-Za-z0-9]", w[4])]
    if not readable:
        return []
    top = min(w[1] for w in readable)
    words = [w for w in words if w[1] >= top + 6]
    left, right = text_column(words)
    words = [w for w in words if left <= (w[0] + w[2]) / 2 <= right]

    # Group into lines by OCR line, then merge OCR lines that share a baseline.
    ocr_lines: dict[tuple, list[tuple]] = {}
    for w in words:
        ocr_lines.setdefault((w[5], w[6]), []).append(w)
    rows: list[list[tuple]] = []
    for line in sorted(ocr_lines.values(), key=lambda ws: sum(w[1] + w[3] for w in ws) / len(ws)):
        middle = sum(w[1] + w[3] for w in line) / (2 * len(line))
        if rows and abs(middle - rows[-1][0]) < 3:
            rows[-1][1].extend(line)
        else:
            rows.append([middle, list(line)])
    lines = [clean(" ".join(w[4] for w in sorted(ws, key=lambda w: w[0]))) for _, ws in rows]
    return [line for line in lines if re.search(r"[A-Za-z0-9]", line)]


def mend_lines(lines: list[str]) -> list[str]:
    """Join a line ending in a broken word or a dash to the line after it."""
    mended: list[str] = []
    for line in lines:
        if mended and (re.search(r"[A-Za-z]-$", mended[-1]) or mended[-1][-1] in (EN_DASH, EM_DASH)):
            mended[-1] = join_lines(mended[-1], line)
        else:
            mended.append(line)
    return mended


def parse_statute(pdf: bytes, entry: dict, max_chars: int = settings.chunk_size) -> SourceDocument:
    public_law, volume = entry["public_law"], entry["volume"]
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pages = [statute_page_lines(page) for page in doc]

    # Laws of the 84th Congress and earlier were printed without the Congress number,
    # and with their chapter number on the same line ("Public Law 381 CHAPTER 867").
    congress, _, number = public_law.partition("-")
    if int(congress) <= 84:
        printed = number
        start_line = re.compile(rf"Public Law {re.escape(number)}( CHAPTER \d+)?")
    else:
        printed = public_law
        start_line = re.compile(rf"Public Law {re.escape(public_law)}")
    start = next(
        ((p, i) for p, lines in enumerate(pages) for i, line in enumerate(lines)
         if start_line.fullmatch(line)),
        None,
    )
    if start is None:
        raise ValueError(f"no line reads 'Public Law {printed}'")
    end = next(
        ((p, i) for p, lines in enumerate(pages) for i, line in enumerate(lines)
         if (p, i) > start and line.startswith("Approved ")),
        None,
    )
    if end is None:
        raise ValueError(f"no 'Approved' line follows 'Public Law {printed}'")

    # The law ends with its approval date; OCR may put scan specks on the same line.
    approved = pages[end[0]][end[1]]
    match = re.match(r"Approved .*?\d{4}\.?", approved)
    pages[end[0]][end[1]] = match.group(0) if match else approved

    units: list[Unit] = []
    for p in range(start[0], end[0] + 1):
        lines = pages[p]
        first = start[1] if p == start[0] else 0
        last = end[1] if p == end[0] else len(lines) - 1
        citation = f"{volume} Stat. {entry['page'] + p}"
        units.append(
            Unit(f"Pub. L. {public_law}, {citation}", citation, entry["name"],
                 mend_lines(lines[first : last + 1]))
        )

    return SourceDocument(
        title=f"Pub. L. {public_law}, {entry['name']} ({volume} Stat. {entry['page']})",
        category=entry["category"],
        source_url=entry["source_url"],
        modified_date=date.fromisoformat(entry["enacted"]),
        chunks=to_chunks(units, max_chars),
    )
