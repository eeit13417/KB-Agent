"""Tests for app/ingest/govinfo.py, written from docs/specs/govinfo.md alone.

Written by the test-writer agent; the implementation was not consulted.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from app.ingest.chunker import ChunkData, SourceDocument
from app.ingest.govinfo import parse_cfr_part, parse_statute

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo"
ENTRIES: dict[str, dict] = json.loads((FIXTURES / "entries.json").read_text(encoding="utf-8"))

CFR_FILES = ["cfr-2010-785.pdf", "cfr-2020-541.pdf", "cfr-1997-541.pdf", "cfr-2010-1904.pdf"]
STAT_FILES = ["stat-88-55.pdf", "stat-91-1245.pdf", "stat-103-938.pdf"]

SECT = "§"  # section sign
EM = "—"  # em dash
LDQ = "“"  # left double quotation mark
RDQ = "”"  # right double quotation mark


# --------------------------------------------------------------------------- helpers


@pytest.fixture(scope="module")
def parse():
    """Parse each (fixture, max_chars) pair once per module.

    Returns a function so that a parser error is raised inside the test body
    (a test failure), not during fixture setup. Successful parses are cached.
    """
    cache: dict[tuple[str, int | None], SourceDocument] = {}

    def get(name: str, max_chars: int | None = None) -> SourceDocument:
        key = (name, max_chars)
        if key not in cache:
            pdf = (FIXTURES / name).read_bytes()
            entry = dict(ENTRIES[name])
            func = parse_cfr_part if name.startswith("cfr-") else parse_statute
            if max_chars is None:
                cache[key] = func(pdf, entry)
            else:
                cache[key] = func(pdf, entry, max_chars=max_chars)
        return cache[key]

    return get


def norm(text: str) -> str:
    return " ".join(text.split())


def chunks_of(doc: SourceDocument, article_no: str) -> list[ChunkData]:
    return [c for c in doc.chunks if c.article_no == article_no]


def unit_text(doc: SourceDocument, article_no: str) -> str:
    """The contents of all chunks with this article_no, joined with a newline."""
    return "\n".join(c.content for c in chunks_of(doc, article_no))


def distinct_in_order(values) -> list:
    seen: list = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return seen


def all_contents(doc: SourceDocument) -> str:
    return "\n".join(c.content for c in doc.chunks)


# --------------------------------------------------------------------------- CFR 2010 Part 785


def test_cfr_785_document_fields(parse):
    """AC-1: title, category, source_url and modified_date of the 2010 Part 785 edition."""
    doc = parse("cfr-2010-785.pdf")
    assert isinstance(doc, SourceDocument)
    assert doc.title == "29 CFR Part 785 (2010 edition)"
    assert doc.category == "Wage and hour (FLSA)"
    assert doc.source_url == ENTRIES["cfr-2010-785.pdf"]["source_url"]
    assert doc.modified_date == date(2010, 7, 1)


def test_cfr_785_article_numbers_are_sections_1_to_50(parse):
    """AC-2: distinct article_no values are exactly § 785.1 .. § 785.50 in order."""
    doc = parse("cfr-2010-785.pdf")
    expected = [f"{SECT} 785.{n}" for n in range(1, 51)]
    assert distinct_in_order(c.article_no for c in doc.chunks) == expected


def test_cfr_785_no_neighbouring_parts(parse):
    """AC-2: no chunk comes from Part 784 (§ 784.156) or Part 786 (§ 786.1)."""
    doc = parse("cfr-2010-785.pdf")
    for c in doc.chunks:
        assert not c.article_no.startswith(f"{SECT} 784.")
        assert not c.article_no.startswith(f"{SECT} 786.")
        assert f"{SECT} 784.156" not in c.content
        assert f"{SECT} 786.1" not in c.content


AC3_PARAGRAPH = (
    "Section 6 of the Fair Labor Standards Act of 1938 (29 U.S.C. 206) requires that each "
    "employee, not specifically exempted, who is engaged in commerce, or in the production of "
    "goods for commerce, or who is employed in an enterprise engaged in commerce, or in the "
    "production of goods for commerce receive a specified minimum wage. Section 7 of the Act "
    "(29 U.S.C. 207) provides that persons may not be employed for more than a stated number "
    "of hours a week without receiving at least one and one-half times their regular rate of "
    "pay for the overtime hours. The amount of money an employee should receive cannot be "
    "determined without knowing the number of hours worked. This part discusses the "
    "principles involved in determining what constitutes working time. It also seeks to "
    "apply these principles to situations that frequently arise. It cannot include every "
    "possible situation. No inference should be drawn from the fact that a subject or an "
    "illustration is omitted. If doubt arises inquiries should be sent to the Administrator "
    "of the Wage and Hour Division, U.S. Department of Labor, Washington, DC 20210, or to any "
    "area or Regional Office of the Division."
)


def test_cfr_785_section_1_exact_content(parse):
    """AC-3: § 785.1 is one chunk: heading line plus one joined paragraph, source note dropped."""
    doc = parse("cfr-2010-785.pdf")
    chunks = chunks_of(doc, f"{SECT} 785.1")
    assert len(chunks) == 1
    assert chunks[0].content == f"{SECT} 785.1 Introductory statement.\n" + AC3_PARAGRAPH


@pytest.mark.parametrize(
    ("article_no", "chapter"),
    [
        (f"{SECT} 785.1", f"Hours Worked / Subpart A{EM}General Considerations"),
        (
            f"{SECT} 785.11",
            f"Hours Worked / Subpart C{EM}Application of Principles / "
            f"Employees {LDQ}Suffered or Permitted{RDQ} to Work",
        ),
        (
            f"{SECT} 785.15",
            f"Hours Worked / Subpart C{EM}Application of Principles / Waiting Time",
        ),
        (
            f"{SECT} 785.42",
            f"Hours Worked / Subpart C{EM}Application of Principles / Adjusting Grievances, "
            "Medical Attention, Civic and Charitable Work, and Suggestion Systems",
        ),
        (f"{SECT} 785.50", f"Hours Worked / Subpart E{EM}Miscellaneous Provisions"),
    ],
    ids=["785.1", "785.11", "785.15", "785.42", "785.50"],
)
def test_cfr_785_chapters(parse, article_no, chapter):
    """AC-4: the chapter of every chunk of the section."""
    doc = parse("cfr-2010-785.pdf")
    chunks = chunks_of(doc, article_no)
    assert chunks, f"no chunk for {article_no}"
    assert {c.chapter for c in chunks} == {chapter}


def test_cfr_785_paragraph_across_page_is_one_line(parse):
    """AC-5: a paragraph continued onto the next page is one line of the § 785.9 text."""
    doc = parse("cfr-2010-785.pdf")
    lines = unit_text(doc, f"{SECT} 785.9").split("\n")
    needle = (
        f"See {SECT}{SECT} 790.6 to 790.8 of this chapter. Section 4 of the Portal-to-Portal "
        "Act does not affect the computation of hours worked within the"
    )
    assert any(needle in line for line in lines)


def test_cfr_785_section_9_has_two_body_lines(parse):
    """AC-5: besides headings, the § 785.9 text has exactly the (a) and (b) paragraphs."""
    doc = parse("cfr-2010-785.pdf")
    chunks = chunks_of(doc, f"{SECT} 785.9")
    assert chunks
    body = [line for c in chunks for line in c.content.split("\n")[1:]]
    assert len(body) == 2
    assert body[0].startswith("(a) The Portal-to-Portal Act.")
    assert body[1].startswith("(b) Section 3(o) of the Fair Labor Standards Act.")


def test_cfr_785_section_50_heading(parse):
    """AC-6: every § 785.50 chunk's first line is the full (multi-line) heading."""
    doc = parse("cfr-2010-785.pdf")
    chunks = chunks_of(doc, f"{SECT} 785.50")
    assert chunks
    for c in chunks:
        assert c.content.split("\n")[0] == f"{SECT} 785.50 Section 4 of the Portal-to-Portal Act."


@pytest.mark.parametrize(
    "forbidden",
    [
        "29 CFR Ch. V",
        "Wage and Hour Division, Labor",
        "VerDate",
        "Jkt 220111",
        "Frm 00",
        "jdjones",
        "AUTHORITY:",
        "SOURCE:",
        "35 FR 15289",
        "‘‘",
        "’’",
    ],
)
def test_cfr_785_no_running_heads_notes_or_doubled_quotes(parse, forbidden):
    """AC-7: running heads, GPO lines, front-matter notes, source notes, doubled quotes are gone."""
    doc = parse("cfr-2010-785.pdf")
    assert doc.chunks
    for c in doc.chunks:
        assert forbidden not in c.content


def test_cfr_785_small_max_chars_splits_section_50(parse):
    """AC-8: with max_chars=1000, § 785.50 splits, each piece repeats the heading, indexes stay dense."""
    doc = parse("cfr-2010-785.pdf", max_chars=1000)
    chunks = chunks_of(doc, f"{SECT} 785.50")
    assert len(chunks) > 1
    for c in chunks:
        assert c.content.startswith(f"{SECT} 785.50 Section 4 of the Portal-to-Portal Act.\n")
    assert [c.chunk_index for c in doc.chunks] == list(range(len(doc.chunks)))


# --------------------------------------------------------------------------- CFR 2020 Part 541


def test_cfr_2020_541_document_fields(parse):
    """AC-9: title and modified_date of the 2020 Part 541 edition."""
    doc = parse("cfr-2020-541.pdf")
    assert doc.title == "29 CFR Part 541 (2020 edition)"
    assert doc.modified_date == date(2020, 7, 1)


def test_cfr_2020_541_starts_at_part_heading(parse):
    """AC-10: first chunk is § 541.0; the previous part's source note (27 FR 400) is dropped."""
    doc = parse("cfr-2020-541.pdf")
    assert doc.chunks
    assert doc.chunks[0].article_no == f"{SECT} 541.0"
    for c in doc.chunks:
        assert "27 FR 400" not in c.content


def test_cfr_2020_541_section_600_chapter(parse):
    """AC-11: chapter of § 541.600 is the title-cased multi-line part name plus Subpart G."""
    doc = parse("cfr-2020-541.pdf")
    chunks = chunks_of(doc, f"{SECT} 541.600")
    assert chunks
    expected = (
        "Defining and Delimiting the Exemptions for Executive, Administrative, Professional, "
        f"Computer and Outside Sales Employees / Subpart G{EM}Salary Requirements"
    )
    assert {c.chapter for c in chunks} == {expected}


def test_cfr_2020_541_salary_threshold(parse):
    """AC-12: § 541.600 states the $684 per week threshold."""
    doc = parse("cfr-2020-541.pdf")
    text = norm(unit_text(doc, f"{SECT} 541.600"))
    assert (
        "an employee must be compensated on a salary basis at a rate of not less than "
        "$684 per week" in text
    )


def test_cfr_2020_541_reserved_section_skipped(parse):
    """AC-13: § 541.607 [Reserved] produces no chunk."""
    doc = parse("cfr-2020-541.pdf")
    assert doc.chunks
    assert all(c.article_no != f"{SECT} 541.607" for c in doc.chunks)


# --------------------------------------------------------------------------- CFR 1997 Part 541


def test_cfr_1997_541_document_fields(parse):
    """AC-14: title and modified_date of the 1997 Part 541 edition."""
    doc = parse("cfr-1997-541.pdf")
    assert doc.title == "29 CFR Part 541 (1997 edition)"
    assert doc.modified_date == date(1997, 7, 1)


def test_cfr_1997_541_each_section_is_one_run(parse):
    """AC-15: no article_no appears in two runs; § 541.1 and § 541.118 each form one unit."""
    doc = parse("cfr-1997-541.pdf")
    runs: list[str] = []
    for c in doc.chunks:
        if not runs or runs[-1] != c.article_no:
            runs.append(c.article_no)
    assert len(runs) == len(set(runs))
    assert f"{SECT} 541.1" in runs
    assert f"{SECT} 541.118" in runs


def test_cfr_1997_541_postponed_text_stays_with_section(parse):
    """AC-16: § 541.1 holds $155, the postponement note, and the $225 version, in that order."""
    doc = parse("cfr-1997-541.pdf")
    text = norm(unit_text(doc, f"{SECT} 541.1"))
    phrases = [
        "not less than $155 per week",
        "the effective date was postponed indefinitely",
        "not less than $225 per week beginning February 13, 1981",
    ]
    positions = [text.find(p) for p in phrases]
    assert all(p >= 0 for p in positions), positions
    assert positions == sorted(positions)


def test_cfr_1997_541_chapter_with_converted_quotes(parse):
    """AC-17: § 541.1 chapter: title-cased part name with curly quotes, then Subpart A."""
    doc = parse("cfr-1997-541.pdf")
    chunks = chunks_of(doc, f"{SECT} 541.1")
    assert chunks
    for c in chunks:
        assert c.chapter.startswith(
            f"Defining and Delimiting the Terms {LDQ}Any Employee Employed in a Bona Fide Executive"
        )
        assert c.chapter.endswith(f" / Subpart A{EM}General Regulations")


# --------------------------------------------------------------------------- CFR 2010 Part 1904

APPENDIX_NO = "Non-Mandatory Appendix A to Subpart B of Part 1904"


def test_cfr_1904_appendix_unit(parse):
    """AC-18: appendix unit exists with its article_no, chapter and title-cased heading."""
    doc = parse("cfr-2010-1904.pdf")
    chunks = chunks_of(doc, APPENDIX_NO)
    assert chunks
    for c in chunks:
        assert c.chapter == (
            "Recording and Reporting Occupational Injuries and Illnesses / "
            f"Subpart B{EM}Scope"
        )
        assert c.content.split("\n")[0] == f"{APPENDIX_NO}{EM}Partially Exempt Industries"


def test_cfr_1904_appendix_position(parse):
    """AC-19: the appendix comes right after § 1904.3 and right before § 1904.4."""
    doc = parse("cfr-2010-1904.pdf")
    order = distinct_in_order(c.article_no for c in doc.chunks)
    assert APPENDIX_NO in order
    i = order.index(APPENDIX_NO)
    assert 0 < i < len(order) - 1
    assert order[i - 1] == f"{SECT} 1904.3"
    assert order[i + 1] == f"{SECT} 1904.4"


def test_cfr_1904_table_rows(parse):
    """AC-20: table rows are ' | '-joined lines without dot leaders."""
    doc = parse("cfr-2010-1904.pdf")
    lines = unit_text(doc, APPENDIX_NO).split("\n")
    assert "SIC code | Industry description" in lines
    assert "525 | Hardware Stores" in lines


def test_cfr_1904_no_dot_leaders(parse):
    """AC-20: no chunk in the document contains '....'."""
    doc = parse("cfr-2010-1904.pdf")
    assert doc.chunks
    for c in doc.chunks:
        assert "...." not in c.content


# --------------------------------------------------------------------------- Statutes


def test_stat_88_55_document_fields(parse):
    """AC-21: title, category, source_url, modified_date and chapter of Pub. L. 93-259."""
    doc = parse("stat-88-55.pdf")
    assert doc.title == "Pub. L. 93-259, Fair Labor Standards Amendments of 1974 (88 Stat. 55)"
    assert doc.category == "Wage and hour (FLSA)"
    assert doc.source_url == ENTRIES["stat-88-55.pdf"]["source_url"]
    assert doc.modified_date == date(1974, 4, 8)
    assert doc.chunks
    for c in doc.chunks:
        assert c.chapter == "Fair Labor Standards Amendments of 1974"


@pytest.mark.parametrize(
    ("name", "volume", "first", "last"),
    [
        ("stat-88-55.pdf", 88, 55, 76),
        ("stat-91-1245.pdf", 91, 1245, 1253),
        ("stat-103-938.pdf", 103, 938, 945),
    ],
)
def test_stat_pages_are_units(parse, name, volume, first, last):
    """AC-22: one unit per Statutes at Large page, in order, each chunk headed by the citation."""
    doc = parse(name)
    expected = [f"{volume} Stat. {p}" for p in range(first, last + 1)]
    assert distinct_in_order(c.article_no for c in doc.chunks) == expected
    public_law = ENTRIES[name]["public_law"]
    for c in doc.chunks:
        assert c.content.startswith(f"Pub. L. {public_law}, {c.article_no}\n")


def test_stat_88_55_start(parse):
    """AC-23: text starts at 'Public Law 93-259'; the end of Pub. L. 93-258 is dropped."""
    doc = parse("stat-88-55.pdf")
    assert doc.chunks
    first = doc.chunks[0].content
    assert "\n" in first
    assert first.split("\n", 1)[1].startswith("Public Law 93-259")
    for c in doc.chunks:
        assert "administrative costs" not in c.content


@pytest.mark.parametrize(
    ("name", "ending"),
    [
        ("stat-88-55.pdf", "Approved April 8, 1974."),
        ("stat-91-1245.pdf", "Approved November 1, 1977."),
        ("stat-103-938.pdf", "Approved November 17, 1989."),
    ],
)
def test_stat_end(parse, name, ending):
    """AC-24: the last chunk ends with the 'Approved' line; no legislative history follows."""
    doc = parse(name)
    assert doc.chunks
    assert norm(doc.chunks[-1].content).endswith(ending)
    for c in doc.chunks:
        assert "LEGISLATIVE HISTORY" not in c.content


def test_stat_88_55_next_laws_dropped(parse):
    """AC-24: nothing from Pub. L. 93-260 (the widow provisions) in stat-88-55.pdf."""
    doc = parse("stat-88-55.pdf")
    assert doc.chunks
    for c in doc.chunks:
        assert "Public Law 93-260" not in c.content
        assert "widow" not in c.content


@pytest.mark.parametrize(
    ("name", "phrase"),
    [
        (
            "stat-88-55.pdf",
            'This Act may be cited as the "Fair Labor Standards Amendments of 1974"',
        ),
        (
            "stat-88-55.pdf",
            "not less than $2 an hour during the period ending December 31,1974",
        ),
        (
            "stat-91-1245.pdf",
            "not less than $2.65 an hour during the year beginning January 1, 1978",
        ),
        (
            "stat-91-1245.pdf",
            "shall take such administrative action as may be necessary for the "
            "implementation of the amendments made by this Act",
        ),
        (
            "stat-103-938.pdf",
            "not less than $3.80 an hour during the year beginning April 1, 1990",
        ),
    ],
)
def test_stat_text(parse, name, phrase):
    """AC-25: key statutory text is present (broken words joined, merged marginal notes removed)."""
    doc = parse(name)
    assert phrase in norm(all_contents(doc))


@pytest.mark.parametrize(
    ("name", "forbidden"),
    [
        ("stat-88-55.pdf", "88 STAT"),
        ("stat-88-55.pdf", "PUBLIC LAW 93-259"),
        ("stat-88-55.pdf", "29 use"),
        ("stat-88-55.pdf", "29 u s e"),
        ("stat-88-55.pdf", "Ante, p."),
        ("stat-91-1245.pdf", "91 STAT"),
        ("stat-91-1245.pdf", "NOV. 1, 1977"),
        ("stat-91-1245.pdf", "USC201"),
        ("stat-91-1245.pdf", "USC203"),
        ("stat-103-938.pdf", "103 STAT"),
        ("stat-103-938.pdf", "NOV. 17, 1989"),
    ],
)
def test_stat_no_running_heads_or_marginal_notes(parse, name, forbidden):
    """AC-26: running heads and marginal notes never reach a chunk."""
    doc = parse(name)
    assert doc.chunks
    for c in doc.chunks:
        assert forbidden not in c.content


# --------------------------------------------------------------------------- Errors


def test_cfr_missing_part_heading_raises():
    """AC-27: parse_cfr_part raises ValueError when the PDF has no PART 999— heading."""
    pdf = (FIXTURES / "cfr-2010-785.pdf").read_bytes()
    entry = dict(ENTRIES["cfr-2010-785.pdf"])
    entry["part"] = "999"
    with pytest.raises(ValueError):
        parse_cfr_part(pdf, entry)


def test_statute_missing_public_law_raises():
    """AC-28: parse_statute raises ValueError when no line reads 'Public Law 93-999'."""
    pdf = (FIXTURES / "stat-88-55.pdf").read_bytes()
    entry = dict(ENTRIES["stat-88-55.pdf"])
    entry["public_law"] = "93-999"
    with pytest.raises(ValueError):
        parse_statute(pdf, entry)


# --------------------------------------------------------------------------- General


@pytest.mark.parametrize("name", CFR_FILES + STAT_FILES)
def test_chunk_indexes_and_field_lengths(parse, name):
    """AC-29: dense chunk_index from 0; chapter <= 500 chars; article_no <= 50 chars."""
    doc = parse(name)
    assert doc.chunks
    assert [c.chunk_index for c in doc.chunks] == list(range(len(doc.chunks)))
    for c in doc.chunks:
        assert c.chapter is None or len(c.chapter) <= 500
        assert len(c.article_no) <= 50
