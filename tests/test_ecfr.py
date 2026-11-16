from app.ingest.ecfr import chunk_part

PART = """<DIV5 N="999" TYPE="PART"><HEAD>PART 999\u2014HOURS WORKED UNDER THE ACT</HEAD>
<DIV8 N="999.0" TYPE="SECTION"><HEAD>\u00a7 999.0 Scope.</HEAD><P>Applies to everyone.</P></DIV8>
<DIV6 N="A" TYPE="SUBPART"><HEAD>Subpart A\u2014General</HEAD>
  <DIV7 TYPE="SUBJGRP"><HEAD>Waiting Time</HEAD>
    <DIV8 N="999.1" TYPE="SECTION"><HEAD>\u00a7 999.1 On duty.</HEAD><P>Waiting is <I>work</I>.</P>
      <CITA TYPE="N">[35 FR 15289, Oct. 1, 1970]</CITA></DIV8>
  </DIV7>
  <DIV8 N="999.2" TYPE="SECTION"><HEAD>\u00a7 999.2 [Reserved]</HEAD></DIV8>
  <DIV8 N="999.3" TYPE="SECTION"><HEAD>\u00a7 999.3 Rates.</HEAD><P>See the table.</P>
    <DIV><TABLE><TR><TH>Age</TH><TH>Rate</TH></TR><TR><TD>16</TD><TD>$4.25</TD></TR></TABLE></DIV>
  </DIV8>
</DIV6>
<DIV9 N="Appendix A to Part 999" TYPE="APPENDIX"><HEAD>Appendix A to Part 999\u2014Notice</HEAD>
  <P>Post this notice.</P></DIV9>
</DIV5>""".encode()


def by_section(max_chars: int = 2000) -> dict:
    return {c.article_no: c for c in chunk_part(PART, max_chars).chunks}


def test_part_number_and_name():
    part = chunk_part(PART, 2000)
    assert part.number == "999"
    assert part.name == "Hours Worked under the Act"


def test_heading_path_and_reserved_sections():
    chapters = {no: c.chapter for no, c in by_section().items()}
    assert chapters == {
        "\u00a7 999.0": "Hours Worked under the Act",
        "\u00a7 999.1": "Hours Worked under the Act / Subpart A\u2014General / Waiting Time",
        "\u00a7 999.3": "Hours Worked under the Act / Subpart A\u2014General",
        "Appendix A to Part 999": "Hours Worked under the Act",
    }



def test_source_notes_dropped_and_inline_text_kept():
    content = by_section()["\u00a7 999.1"].content
    assert content == "\u00a7 999.1 On duty.\nWaiting is work."


def test_table_rows_keep_their_cells():
    assert "16 | $4.25" in by_section()["\u00a7 999.3"].content


def test_long_section_split_by_paragraph_with_heading_repeated():
    paragraphs = [f"Paragraph {i} " + "x" * 40 for i in range(3)]
    xml = (
        '<DIV5 N="1" TYPE="PART"><HEAD>PART 1\u2014X</HEAD><DIV8 N="1.1" TYPE="SECTION">'
        "<HEAD>\u00a7 1.1 Long.</HEAD>" + "".join(f"<P>{p}</P>" for p in paragraphs) + "</DIV8></DIV5>"
    ).encode()
    chunks = chunk_part(xml, max_chars=80).chunks
    assert len(chunks) == 3
    assert all(c.content.startswith("\u00a7 1.1 Long.\n") for c in chunks)
    assert [c.content.splitlines()[1] for c in chunks] == paragraphs
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
