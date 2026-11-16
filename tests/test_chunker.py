from app.ingest.chunker import split_article

LEAD = "\u00a7 1.1 Prohibited practices."


def test_short_text_stays_whole():
    assert split_article(f"{LEAD}\nBody.", 100) == [f"{LEAD}\nBody."]


def test_long_text_repeats_heading_and_loses_nothing():
    items = [f"({i}) " + "x" * 40 for i in range(1, 11)]
    parts = split_article(LEAD + "\r\n" + "\r\n".join(items), max_chars=200)
    assert len(parts) > 1
    assert all(p.startswith(LEAD + "\n") for p in parts)
    assert all(len(p) <= 200 for p in parts)
    assert [line for p in parts for line in p.splitlines()[1:]] == items


def test_paragraph_longer_than_limit_is_kept_whole():
    paragraph = "x" * 300
    assert split_article(f"{LEAD}\n{paragraph}", 100) == [f"{LEAD}\n{paragraph}"]
