from app.ingest.chunker import chunk_law


def make_law(*articles: tuple[str, str, str]) -> dict:
    return {
        "LawArticles": [
            {"ArticleType": kind, "ArticleNo": no, "ArticleContent": content}
            for kind, no, content in articles
        ]
    }


def test_heading_path_resets_lower_levels():
    law = make_law(
        ("C", "", "   第 一 章 總則"),
        ("A", "第 1 條", "甲"),
        ("C", "", "第 二 章 給付"),
        ("C", "", "第 一 節 通則"),
        ("A", "第 2 條", "乙"),
        ("C", "", "第 三 章 附則"),
        ("A", "第 3 條", "丙"),
    )
    chapters = [c.chapter for c in chunk_law(law)]
    assert chapters == ["第 一 章 總則", "第 二 章 給付 / 第 一 節 通則", "第 三 章 附則"]


def test_deleted_articles_are_skipped():
    law = make_law(("A", "第 1 條", "甲"), ("A", "第 2 條", "（刪除）"), ("A", "第 3 條", "丙"))
    chunks = chunk_law(law)
    assert [c.article_no for c in chunks] == ["第 1 條", "第 3 條"]
    assert [c.chunk_index for c in chunks] == [0, 1]


def test_long_article_repeats_lead_line_in_every_part():
    lead = "雇主不得有下列情事："
    items = "\r\n".join(f"{i}、" + "字" * 40 for i in range(1, 11))
    law = make_law(("A", "第 5 條", f"{lead}\r\n{items}"))
    chunks = chunk_law(law, max_chars=200)
    assert len(chunks) > 1
    assert all(c.content.startswith(lead) for c in chunks)
    assert all(len(c.content) <= 200 for c in chunks)
