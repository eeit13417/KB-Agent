"""Tests for eval/metrics.py, written from docs/specs/metrics.md alone."""

import csv
from pathlib import Path

import pytest

from eval.metrics import (
    VERDICTS,
    document_hit,
    parse_sources,
    percentile,
    query_cost,
    source_hit,
    summarize,
)

SECTION = "§"
TESTSET = Path(__file__).resolve().parent.parent / "eval" / "testset.csv"

SUMMARY_KEYS = {
    "n",
    "recall_at_5",
    "accuracy",
    "accuracy_lenient",
    "hallucination_rate",
    "latency_p50",
    "latency_p95",
    "cost_per_query",
    "unjudged",
    "by_type",
}


def _result(type_, behavior, recall_hit, verdict, latency, cost):
    return {
        "type": type_,
        "expected_behavior": behavior,
        "recall_hit": recall_hit,
        "verdict": verdict,
        "latency_s": latency,
        "cost_usd": cost,
    }


def six_results():
    """The six results of the spec's summarize table, in order (index 0 is result #1)."""
    return [
        _result("current", "answer", True, "correct", 1.0, 0.001),
        _result("current", "answer", False, "partial", 2.0, 0.002),
        _result("history", "answer", False, "incorrect", 3.0, 0.003),
        _result("no_answer", "decline", None, "correct", 4.0, 0.001),
        _result("no_answer", "decline", None, "incorrect", 5.0, 0.001),
        _result("injection", "resist", True, "correct", 6.0, 0.004),
    ]


def seventh_result():
    """The seventh result added in AC-12."""
    return _result("current", "answer", True, None, 7.0, 0.0)


# --- parse_sources ---------------------------------------------------------


def test_parse_single_source():
    """AC-1: a single `title | article_no` source is parsed into one pair."""
    assert parse_sources(f"29 CFR Part 541 | {SECTION} 541.600") == [
        ("29 CFR Part 541", f"{SECTION} 541.600")
    ]


def test_parse_two_sources_with_commas_and_extra_spaces():
    """AC-2: titles with commas, parentheses and periods; extra spaces are stripped; order kept."""
    text = (
        "Pub. L. 95-151, Fair Labor Standards Amendments of 1977 (91 Stat. 1245) | 91 Stat. 1249;"
        f"  29 CFR Part 531  |  {SECTION} 531.50 "
    )
    assert parse_sources(text) == [
        (
            "Pub. L. 95-151, Fair Labor Standards Amendments of 1977 (91 Stat. 1245)",
            "91 Stat. 1249",
        ),
        ("29 CFR Part 531", f"{SECTION} 531.50"),
    ]


@pytest.mark.parametrize("text", ["", "   "])
def test_parse_empty_text(text):
    """AC-3: empty or whitespace-only text gives an empty list."""
    assert parse_sources(text) == []


@pytest.mark.parametrize("text", [f"29 CFR Part 541 {SECTION} 541.600", "A | B | C"])
def test_parse_wrong_separator_count_raises(text):
    """AC-4: a part with no ` | ` or with two ` | ` raises ValueError."""
    with pytest.raises(ValueError):
        parse_sources(text)


# --- source_hit / document_hit ----------------------------------------------


def test_source_hit_respects_k():
    """AC-5: a match at position 3 counts with the default k but not with k=2."""
    expected = [("A", f"{SECTION} 1")]
    retrieved = [("B", f"{SECTION} 1"), ("A", f"{SECTION} 2"), ("A", f"{SECTION} 1")]
    assert source_hit(expected, retrieved) is True
    assert source_hit(expected, retrieved, k=2) is False


def test_source_hit_edition_is_part_of_title():
    """AC-6: an edition-qualified title does not match the plain title."""
    assert (
        source_hit(
            [("29 CFR Part 541", f"{SECTION} 541.600")],
            [("29 CFR Part 541 (2020 edition)", f"{SECTION} 541.600")],
        )
        is False
    )


@pytest.mark.parametrize(
    "retrieved",
    [
        [("X", "1"), ("A", f"{SECTION} 1")],
        [("B", f"{SECTION} 2"), ("X", "1")],
    ],
)
def test_source_hit_either_expected_source_is_enough(retrieved):
    """AC-6: with two expected sources, retrieving either one is enough."""
    expected = [("A", f"{SECTION} 1"), ("B", f"{SECTION} 2")]
    assert source_hit(expected, retrieved) is True


def test_source_hit_empty_expected_is_false():
    """AC-6: source_hit with no expected sources is False."""
    assert source_hit([], [("A", f"{SECTION} 1")]) is False


def test_document_hit_compares_titles_only():
    """AC-7: document_hit ignores article_no but compares titles exactly."""
    assert document_hit([("A", f"{SECTION} 1")], [("A", f"{SECTION} 9")]) is True
    assert document_hit([("A", f"{SECTION} 1")], [("A (2020 edition)", f"{SECTION} 1")]) is False


def test_document_hit_respects_k():
    """AC-7: document_hit only looks at the first k retrieved sources."""
    assert document_hit([("A", f"{SECTION} 1")], [("B", "x"), ("A", "y")], k=1) is False


def test_document_hit_empty_expected_is_false():
    """AC-7: document_hit with no expected sources is False (contract: both False when empty)."""
    assert document_hit([], [("A", f"{SECTION} 1")]) is False


# --- percentile / query_cost --------------------------------------------------


def test_percentile_interpolates():
    """AC-8: linear interpolation between closest ranks."""
    assert percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
    assert percentile([1, 2, 3, 4], 95) == pytest.approx(3.85)


def test_percentile_unsorted_input_not_mutated():
    """AC-8: unsorted input gives the same result and is left unchanged."""
    values = [4, 1, 3, 2]
    assert percentile(values, 95) == pytest.approx(3.85)
    assert values == [4, 1, 3, 2]


def test_percentile_single_value():
    """AC-8: a single value is its own percentile."""
    assert percentile([5], 95) == pytest.approx(5)


def test_percentile_bounds_are_min_and_max():
    """AC-8: p = 0 gives the minimum and p = 100 the maximum."""
    values = [4, 1, 3, 2]
    assert percentile(values, 0) == pytest.approx(1)
    assert percentile(values, 100) == pytest.approx(4)


@pytest.mark.parametrize(("values", "p"), [([], 50), ([1], -1), ([1], 101)])
def test_percentile_invalid_input_raises(values, p):
    """AC-9: empty list or p outside [0, 100] raises ValueError."""
    with pytest.raises(ValueError):
        percentile(values, p)


def test_query_cost():
    """AC-10: cost in US dollars from token counts and per-million prices."""
    assert query_cost(2000, 500, 0.15, 0.60) == pytest.approx(0.0006)
    assert query_cost(0, 0, 0.15, 0.60) == 0


# --- summarize ------------------------------------------------------------------


def test_summarize_six_results():
    """AC-11: summary of the six example results."""
    summary = summarize(six_results())
    assert set(summary) == SUMMARY_KEYS
    assert summary["n"] == 6
    assert summary["recall_at_5"] == pytest.approx(0.5)
    assert summary["accuracy"] == pytest.approx(0.5)
    assert summary["accuracy_lenient"] == pytest.approx(0.625)
    assert summary["hallucination_rate"] == pytest.approx(0.5)
    assert summary["latency_p50"] == pytest.approx(3.5)
    assert summary["latency_p95"] == pytest.approx(5.75)
    assert summary["cost_per_query"] == pytest.approx(0.002)
    assert summary["unjudged"] == 0
    assert summary["by_type"] == {
        "current": {"n": 2, "accuracy": pytest.approx(0.5)},
        "history": {"n": 1, "accuracy": pytest.approx(0.0)},
        "no_answer": {"n": 2, "accuracy": pytest.approx(0.5)},
        "injection": {"n": 1, "accuracy": pytest.approx(1.0)},
    }


def test_summarize_by_type_only_present_types():
    """AC-11: by_type has one entry per type present in the results, and no others."""
    summary = summarize(six_results()[:3])
    assert set(summary["by_type"]) == {"current", "history"}


def test_summarize_unjudged_result_left_out():
    """AC-12: an unjudged seventh result counts in n, recall, latency and cost but not accuracy."""
    summary = summarize(six_results() + [seventh_result()])
    assert set(summary) == SUMMARY_KEYS
    assert summary["n"] == 7
    assert summary["unjudged"] == 1
    assert summary["accuracy"] == pytest.approx(0.5)
    assert summary["hallucination_rate"] == pytest.approx(0.5)
    assert summary["recall_at_5"] == pytest.approx(0.6)
    assert summary["latency_p50"] == pytest.approx(4.0)
    assert summary["cost_per_query"] == pytest.approx(0.012 / 7)
    assert summary["by_type"]["current"] == {"n": 3, "accuracy": pytest.approx(0.5)}


def test_summarize_zero_denominators_decline_only():
    """AC-13: with only results 4 and 5, accuracy, accuracy_lenient and recall_at_5 are None."""
    results = six_results()
    summary = summarize([results[3], results[4]])
    assert summary["accuracy"] is None
    assert summary["accuracy_lenient"] is None
    assert summary["recall_at_5"] is None
    assert summary["hallucination_rate"] == pytest.approx(0.5)


def test_summarize_zero_denominators_answer_only():
    """AC-13: with only results 1 and 2, hallucination_rate is None."""
    results = six_results()
    summary = summarize([results[0], results[1]])
    assert summary["hallucination_rate"] is None
    assert summary["accuracy"] == pytest.approx(0.5)


def test_summarize_by_type_unjudged_only_type_is_none():
    """AC-13: a type whose only result is unjudged has by_type accuracy None."""
    results = six_results()
    lone_unjudged = _result("colloquial", "answer", True, None, 2.0, 0.001)
    summary = summarize([results[0], lone_unjudged])
    assert summary["by_type"]["colloquial"] == {"n": 1, "accuracy": None}
    assert summary["by_type"]["current"] == {"n": 1, "accuracy": pytest.approx(1.0)}


def test_summarize_empty_raises():
    """AC-14: summarize([]) raises ValueError."""
    with pytest.raises(ValueError):
        summarize([])


def test_summarize_unknown_verdict_raises():
    """AC-14: a verdict not None and not in VERDICTS raises ValueError."""
    assert "maybe" not in VERDICTS
    bad = _result("current", "answer", True, "maybe", 1.0, 0.001)
    with pytest.raises(ValueError):
        summarize(six_results() + [bad])


def test_summarize_unknown_expected_behavior_raises():
    """AC-14: an expected_behavior other than answer/decline/resist raises ValueError."""
    bad = _result("current", "answer it", True, "correct", 1.0, 0.001)
    with pytest.raises(ValueError):
        summarize(six_results() + [bad])


# --- the real test set ------------------------------------------------------------


def test_testset_sources_parse_and_match_behavior():
    """AC-15: every row parses; answer/resist rows have sources, decline rows none; ids unique; 20 quick."""
    with TESTSET.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows

    for row in rows:
        behavior = row["expected_behavior"]
        assert behavior in ("answer", "decline", "resist"), row["id"]
        sources = parse_sources(row["expected_sources"])
        if behavior in ("answer", "resist"):
            assert len(sources) >= 1, row["id"]
        else:
            assert sources == [], row["id"]

    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert sum(1 for row in rows if row["quick"] == "y") == 20
