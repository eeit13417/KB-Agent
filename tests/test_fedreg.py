"""Tests for app/ingest/fedreg.py, written from docs/specs/fedreg.md."""

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from app.ingest.fedreg import parse_document, select_documents

FIXTURES = Path(__file__).parent / "fixtures" / "fr"

WHD = "wage-and-hour-division"


def _load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _catalog() -> list[dict]:
    return _load_json("catalog-sample.json")


def _entry(document_number: str) -> dict:
    return _load_json("entries.json")[document_number]


def _parse(document_number: str, **kwargs):
    xml = (FIXTURES / f"{document_number}.xml").read_bytes()
    return parse_document(xml, _entry(document_number), **kwargs)


def _numbers(entries: list[dict]) -> list[str]:
    return [e["document_number"] for e in entries]


def _lines(content: str) -> list[str]:
    return content.split("\n")


def _first_line(content: str) -> str:
    return _lines(content)[0]


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_select_documents_exact_result_in_order():
    """AC-1: the sample selects exactly the six expected documents, in catalog order."""
    result = select_documents(_catalog())
    assert _numbers(result) == [
        "2024-08333",
        "2026-07959",
        "2010-2731",
        "2026-08260",
        "2026-15227",
        "2026-17726",
    ]


def test_select_documents_keeps_long_whd_rule():
    """AC-2: a WHD rule is kept whatever its length (2024-08333, 172 pages)."""
    catalog = _catalog()
    long_rule = next(e for e in catalog if e["document_number"] == "2024-08333")
    assert long_rule["page_length"] == 172
    assert "2024-08333" in _numbers(select_documents(catalog))


def test_select_documents_drops_notices():
    """AC-3: notices are dropped for both WHD (2026-21169) and OSHA (2026-23315)."""
    numbers = _numbers(select_documents(_catalog()))
    assert "2026-21169" not in numbers
    assert "2026-23315" not in numbers


def test_select_documents_drops_before_keep_since():
    """AC-4: documents published before KEEP_SINCE are dropped (E9-12436, E9-27004)."""
    numbers = _numbers(select_documents(_catalog()))
    assert "E9-12436" not in numbers
    assert "E9-27004" not in numbers


def test_select_documents_osha_page_limit_inclusive():
    """AC-5: OSHA keeps exactly OSHA_MAX_PAGES pages (2026-08260) and drops 6 pages (2023-05724)."""
    numbers = _numbers(select_documents(_catalog()))
    assert "2026-08260" in numbers
    assert "2023-05724" not in numbers


def test_select_documents_joint_document_once_first_wins():
    """AC-6: 2026-17726 (listed under both agencies) appears once, with the WHD entry kept."""
    result = select_documents(_catalog())
    kept = [e for e in result if e["document_number"] == "2026-17726"]
    assert len(kept) == 1
    assert kept[0]["agency"] == WHD


def test_select_documents_does_not_modify_input():
    """AC-7: the catalog passed in still has its 12 entries (unchanged) after the call."""
    catalog = _catalog()
    before = copy.deepcopy(catalog)
    select_documents(catalog)
    assert len(catalog) == 12
    assert catalog == before


# ---------------------------------------------------------------------------
# Parsing: document fields
# ---------------------------------------------------------------------------


def test_parse_final_rule_document_fields():
    """AC-8: 2026-09839 has the specified title, category, source_url and modified_date."""
    doc = _parse("2026-09839")
    assert doc.title == "FR Doc. 2026-09839 (Final rule, 2026-05-15)"
    assert doc.category == "Federal Register: Wage and hour"
    assert doc.source_url == _entry("2026-09839")["html_url"]
    assert doc.modified_date == date(2026, 5, 15)


def test_parse_proposed_rule_title():
    """AC-9: 2025-12314 is titled as a proposed rule."""
    doc = _parse("2025-12314")
    assert doc.title == "FR Doc. 2025-12314 (Proposed rule, 2025-07-02)"


# ---------------------------------------------------------------------------
# Parsing: units and chunks
# ---------------------------------------------------------------------------


def test_summary_unit_is_chunk_zero():
    """AC-10: chunk 0 of 2026-09839 is the summary unit with Action, Summary and Dates lines."""
    doc = _parse("2026-09839")
    chunk = doc.chunks[0]
    assert chunk.chunk_index == 0
    assert chunk.article_no == "Summary"
    assert chunk.chapter.startswith("Defining and Delimiting the Exemptions for Executive")
    lines = _lines(chunk.content)
    assert lines[0] == chunk.chapter
    assert "Action: Final rule; technical amendment." in lines
    assert "Dates: This rule is effective May 15, 2026." in lines
    assert any(
        line.startswith("Summary: This document implements the judgments of federal courts")
        for line in lines
    )


def test_nested_preamble_heading_unit():
    """AC-11: a chunk for HD2 'C. Judicial Vacatur of the 2024 Rule' under 'I. Background'."""
    doc = _parse("2026-09839")
    matches = [
        c
        for c in doc.chunks
        if c.article_no == "I. Background"
        and _first_line(c.content) == "C. Judicial Vacatur of the 2024 Rule"
        and c.chapter.endswith(" > I. Background > C. Judicial Vacatur of the 2024 Rule")
    ]
    assert matches


def test_heading_followed_directly_by_heading_has_no_unit():
    """AC-12: no chunk of 2026-09839 starts with 'I. Background' (no lines before next heading)."""
    doc = _parse("2026-09839")
    assert doc.chunks
    assert all(_first_line(c.content) != "I. Background" for c in doc.chunks)


def test_heading_with_own_paragraph_has_unit():
    """AC-13: 2025-12314 has a chunk starting with 'II. Discussion'."""
    doc = _parse("2025-12314")
    assert any(_first_line(c.content) == "II. Discussion" for c in doc.chunks)


def test_regulatory_text_section_unit():
    """AC-14: § 541.600 becomes a regulatory text unit under 29 CFR Part 541."""
    doc = _parse("2026-09839")
    matches = [
        c
        for c in doc.chunks
        if c.article_no == "§ 541.600"
        and _first_line(c.content) == "§ 541.600 Amount of salary required."
        and c.chapter.endswith(" > Regulatory text > 29 CFR Part 541")
    ]
    assert matches
    assert any("$684 per week" in c.content for c in matches)


def test_removed_section_has_no_unit():
    """AC-15: § 541.5 [Removed] has no body and produces no chunk."""
    doc = _parse("2026-09839")
    assert doc.chunks
    assert all(c.article_no != "§ 541.5" for c in doc.chunks)


@pytest.mark.parametrize(
    "excluded",
    [
        "8. Revise § 541.600",
        "(202) 693-0406",
        "Andrew B. Rogers",
        "Filed 5-14-26",
        "29 U.S.C. 206(a), 207(a)",
        "List of Subjects",
    ],
)
def test_excluded_elements_not_in_chunks(excluded):
    """AC-16: amendment instructions, contacts, signatures, FR Doc line, footnotes, LSTSUB are dropped."""
    doc = _parse("2026-09839")
    assert doc.chunks
    assert all(excluded not in c.content for c in doc.chunks)


def test_footnote_markers_leave_no_trace():
    """AC-17: text around a footnote marker is joined with no leftover marker."""
    doc = _parse("2026-09839")
    assert any(
        "over 40 in a workweek. The FLSA includes a number of exemptions" in c.content
        for c in doc.chunks
    )


def test_gpotable_becomes_lines():
    """AC-18: GPOTABLE headers and rows become ' | '-joined lines."""
    doc = _parse("2024-00253")
    header = "Violations occurring | Penalty assessed | Which penalty level applies"
    row = "After March 23, 2018 | After January 15, 2024 | January 15, 2024 level."
    assert any(
        header in _lines(c.content) and row in _lines(c.content) for c in doc.chunks
    )


def test_preamble_table_of_contents_dropped():
    """AC-19: the 'Preamble Table of Contents' HD1 section of 2024-00253 is dropped."""
    doc = _parse("2024-00253")
    assert doc.chunks
    assert all("Preamble Table of Contents" not in c.content for c in doc.chunks)
    assert all("Preamble Table of Contents" not in (c.chapter or "") for c in doc.chunks)
    assert all("Preamble Table of Contents" not in c.article_no for c in doc.chunks)


def test_add_element_dropped():
    """AC-20: 2025-12314's ADD comment instructions ('Electronic Comments') are dropped."""
    doc = _parse("2025-12314")
    assert doc.chunks
    assert all("Electronic Comments" not in c.content for c in doc.chunks)


def test_joint_rule_with_different_preamble_order():
    """AC-21: 2026-17726 parses, with the expected title and chunk 0 chapter."""
    doc = _parse("2026-17726")
    assert doc.title == "FR Doc. 2026-17726 (Final rule, 2026-08-31)"
    assert doc.chunks[0].chapter == "Rescission of Coordinated Enforcement Regulations"


def _group_units(chunks):
    """Group consecutive chunks by (chapter, article_no, first line); return keys and body lines."""
    units: list[tuple[tuple, list[str]]] = []
    for c in chunks:
        lines = _lines(c.content)
        key = (c.chapter, c.article_no, lines[0])
        if units and units[-1][0] == key:
            units[-1][1].extend(lines[1:])
        else:
            units.append((key, list(lines[1:])))
    return units


def test_small_max_chars_splits_without_losing_lines():
    """AC-22: with max_chars=500, indexes are 0..n-1 and each unit's pieces rejoin to its body."""
    small = _parse("2025-12314", max_chars=500)
    default = _parse("2025-12314")

    assert [c.chunk_index for c in small.chunks] == list(range(len(small.chunks)))
    assert [c.chunk_index for c in default.chunks] == list(range(len(default.chunks)))
    # A smaller limit must actually split some units in this document.
    assert len(small.chunks) > len(default.chunks)

    small_units = _group_units(small.chunks)
    default_units = _group_units(default.chunks)

    # Every chunk of a unit starts with that unit's heading: the units (and their headings)
    # found by grouping the small parse are exactly the units of the default parse.
    assert [key for key, _ in small_units] == [key for key, _ in default_units]
    # And each unit's pieces, with the repeated heading removed, rejoin to the same body.
    for (key, small_body), (_, default_body) in zip(small_units, default_units):
        assert small_body == default_body, key


# ---------------------------------------------------------------------------
# Errors and whitespace
# ---------------------------------------------------------------------------


def test_non_rule_root_raises_value_error():
    """AC-23: a root element other than RULE or PRORULE raises ValueError."""
    with pytest.raises(ValueError):
        parse_document(b"<NOTICE><PREAMB/></NOTICE>", _entry("2026-09839"))


def test_no_thin_space_in_output():
    """AC-24: no article_no, chapter or content of 2026-09839 contains U+2009."""
    doc = _parse("2026-09839")
    assert doc.chunks
    for c in doc.chunks:
        assert "\u2009" not in c.article_no
        assert "\u2009" not in (c.chapter or "")
        assert "\u2009" not in c.content


# ---------------------------------------------------------------------------
# Column-size truncation
# ---------------------------------------------------------------------------


def _text_of_length(word: str, length: int) -> str:
    """Numbered words ('Word001 Word002 ...') cut to exactly `length` chars, no edge spaces."""
    words = " ".join(f"{word}{i:03d}" for i in range(1, length))
    text = words[:length]
    if text.endswith(" "):
        text = text[:-1] + "X"
    assert len(text) == length and text == text.strip()
    return text


def test_long_chapter_and_article_no_are_truncated_for_every_unit():
    """AC-25: chapter is cut to 500 and article_no to 50 chars for every unit type."""
    subject = _text_of_length("Subject", 600)
    heading = _text_of_length("Heading", 80)
    sectno = _text_of_length("Sectno", 60)
    xml = f"""<RULE>
    <PREAMB>
        <SUBJECT>{subject}</SUBJECT>
        <SUM>
            <HD SOURCE="HED">SUMMARY:</HD>
            <P>This summary paragraph describes the long-subject rule.</P>
        </SUM>
    </PREAMB>
    <SUPLINF>
        <HD SOURCE="HD1">{heading}</HD>
        <P>This preamble paragraph sits under the long heading.</P>
        <REGTEXT TITLE="29" PART="541">
            <SECTION>
                <SECTNO>{sectno}</SECTNO>
                <SUBJECT>Long section number rule.</SUBJECT>
                <P>This regulatory paragraph sits under the long section number.</P>
            </SECTION>
        </REGTEXT>
    </SUPLINF>
</RULE>""".encode("utf-8")

    doc = parse_document(xml, _entry("2026-09839"))

    summary_full_chapter = subject
    preamble_full_chapter = f"{subject} > {heading}"
    regulatory_full_chapter = f"{subject} > Regulatory text > 29 CFR Part 541"

    summary = [c for c in doc.chunks if _first_line(c.content) == subject]
    preamble = [c for c in doc.chunks if _first_line(c.content) == heading]
    regulatory = [
        c
        for c in doc.chunks
        if _first_line(c.content) == f"{sectno} Long section number rule."
    ]
    # There is a summary chunk, a preamble chunk and a regulatory text chunk.
    assert summary, "no summary chunk"
    assert preamble, "no preamble chunk"
    assert regulatory, "no regulatory text chunk"

    expected = [
        (summary, summary_full_chapter, "Summary"),
        (preamble, preamble_full_chapter, heading),
        (regulatory, regulatory_full_chapter, sectno),
    ]
    for chunks, full_chapter, full_article_no in expected:
        for c in chunks:
            assert len(c.chapter) <= 500
            assert c.chapter == full_chapter[:500]
            assert len(c.article_no) <= 50
            assert c.article_no == full_article_no[:50]

    # Every chunk in the document obeys the column sizes.
    for c in doc.chunks:
        assert len(c.chapter or "") <= 500
        assert len(c.article_no) <= 50

    # The summary chunk's content still starts with the full 600-character subject line.
    assert doc.chunks[0].content.split("\n")[0] == subject
    assert len(_first_line(doc.chunks[0].content)) == 600


# ---------------------------------------------------------------------------
# Older and unusual document layouts
# ---------------------------------------------------------------------------


def test_dates_element_gives_dates_line():
    """AC-26: 2016-26003 uses DATES; chunk 0 is the summary with the Dates line after Action."""
    doc = _parse("2016-26003")
    chunk = doc.chunks[0]
    assert chunk.article_no == "Summary"
    lines = _lines(chunk.content)
    action = "Action: Notice of public meeting."
    dates = "Dates: Wednesday November 16, 2016."
    assert action in lines
    assert dates in lines
    assert lines.index(action) < lines.index(dates)


def test_older_osha_proposed_rule_document_fields():
    """AC-26: 2016-26003 has the OSHA category and the proposed-rule title."""
    doc = _parse("2016-26003")
    assert doc.category == "Federal Register: Safety and health"
    assert doc.title == "FR Doc. 2016-26003 (Proposed rule, 2016-10-28)"


def test_lines_before_first_hd1_form_supplementary_information_unit():
    """AC-27: SUPLINF paragraphs with no HD1 form a 'Supplementary information' unit."""
    doc = _parse("2016-26003")
    matches = [
        c
        for c in doc.chunks
        if c.article_no == "Supplementary information"
        and _first_line(c.content) == "Supplementary information"
        and c.chapter
        == "Informal Discussion on Hazard Communication Rulemaking > Supplementary information"
    ]
    assert matches
    assert any("Advanced Meeting Registration:" in c.content for c in matches)


@pytest.mark.parametrize(
    "excluded",
    ["Signed at Washington, DC, on October 24, 2016", "ruskin.maureen@dol.gov"],
)
def test_older_osha_signature_and_contact_dropped(excluded):
    """AC-27: 2016-26003's signature and contact text appear in no chunk."""
    doc = _parse("2016-26003")
    assert doc.chunks
    assert all(excluded not in c.content for c in doc.chunks)


def test_correction_document_regtext_inside_preamb():
    """AC-28: 2012-15868 (REGTEXT inside PREAMB, no summary elements) has exactly one chunk."""
    doc = _parse("2012-15868")
    assert len(doc.chunks) == 1
    chunk = doc.chunks[0]
    assert chunk.chunk_index == 0
    assert chunk.article_no == "§ 570.65"
    assert chunk.chapter == (
        "Child Labor Regulations, Orders and Statements of Interpretation"
        " > Regulatory text > 29 CFR Part 570"
    )
    assert _first_line(chunk.content) == "§ 570.65 [CORRECTED]"
    assert "Occupations involving the operation of circular saws" in chunk.content


def test_correction_document_has_no_subject_only_summary():
    """AC-28: 2012-15868 has no Summary chunk and no chunk holding only the subject."""
    doc = _parse("2012-15868")
    subject = "Child Labor Regulations, Orders and Statements of Interpretation"
    assert all(c.article_no != "Summary" for c in doc.chunks)
    assert all(c.content.strip() != subject for c in doc.chunks)
