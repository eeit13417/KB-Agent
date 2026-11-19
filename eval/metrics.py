"""The five evaluation numbers, computed from per-question results.

Spec: docs/specs/metrics.md
"""

import math

Source = tuple[str, str]  # (document title, article_no)

VERDICTS: tuple[str, ...] = ("correct", "partial", "incorrect")

BEHAVIORS: tuple[str, ...] = ("answer", "decline", "resist")

_LENIENT_SCORE = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}


def parse_sources(text: str) -> list[Source]:
    """Parse an `expected_sources` cell: `title | article_no` parts separated by `;`."""
    sources: list[Source] = []
    for part in text.split(";"):
        if not part.strip():
            continue
        if part.count(" | ") != 1:
            raise ValueError(f"expected exactly one ' | ' in source {part!r}")
        title, article_no = part.split(" | ")
        sources.append((title.strip(), article_no.strip()))
    return sources


def source_hit(expected: list[Source], retrieved: list[Source], k: int = 5) -> bool:
    """True when an expected (title, article_no) pair is among the first k retrieved."""
    top = set(retrieved[:k])
    return any(source in top for source in expected)


def document_hit(expected: list[Source], retrieved: list[Source], k: int = 5) -> bool:
    """True when an expected title is among the titles of the first k retrieved."""
    top = {title for title, _ in retrieved[:k]}
    return any(title in top for title, _ in expected)


def percentile(values: list[float], p: float) -> float:
    """Linear interpolation between closest ranks (numpy.percentile's default)."""
    if not values:
        raise ValueError("percentile of an empty list")
    if not 0 <= p <= 100:
        raise ValueError(f"p must be in [0, 100], got {p}")
    ordered = sorted(values)
    rank = p / 100 * (len(ordered) - 1)
    low = math.floor(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (rank - low) * (ordered[high] - ordered[low])


def query_cost(
    prompt_tokens: int, completion_tokens: int, input_per_million: float, output_per_million: float
) -> float:
    """Cost of one query in US dollars."""
    return (
        prompt_tokens * input_per_million / 1_000_000
        + completion_tokens * output_per_million / 1_000_000
    )


def _share(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def summarize(results: list[dict]) -> dict:
    """Aggregate per-question results into the evaluation's reported numbers."""
    if not results:
        raise ValueError("cannot summarize an empty list of results")
    for result in results:
        if result["verdict"] is not None and result["verdict"] not in VERDICTS:
            raise ValueError(f"unknown verdict {result['verdict']!r}")
        if result["expected_behavior"] not in BEHAVIORS:
            raise ValueError(f"unknown expected_behavior {result['expected_behavior']!r}")

    with_recall = [r["recall_hit"] for r in results if r["recall_hit"] is not None]
    judged = [r for r in results if r["verdict"] is not None]
    answerable = [r for r in judged if r["expected_behavior"] != "decline"]
    declines = [r for r in judged if r["expected_behavior"] == "decline"]
    latencies = [r["latency_s"] for r in results]

    by_type: dict[str, dict] = {}
    for type_ in dict.fromkeys(r["type"] for r in results):
        of_type = [r for r in results if r["type"] == type_]
        judged_of_type = [r for r in of_type if r["verdict"] is not None]
        by_type[type_] = {
            "n": len(of_type),
            "accuracy": _share(
                sum(r["verdict"] == "correct" for r in judged_of_type), len(judged_of_type)
            ),
        }

    return {
        "n": len(results),
        "recall_at_5": _share(sum(1 for hit in with_recall if hit), len(with_recall)),
        "accuracy": _share(sum(r["verdict"] == "correct" for r in answerable), len(answerable)),
        "accuracy_lenient": _share(
            sum(_LENIENT_SCORE[r["verdict"]] for r in answerable), len(answerable)
        ),
        "hallucination_rate": _share(
            sum(r["verdict"] != "correct" for r in declines), len(declines)
        ),
        "latency_p50": percentile(latencies, 50),
        "latency_p95": percentile(latencies, 95),
        "cost_per_query": sum(r["cost_usd"] for r in results) / len(results),
        "unjudged": len(results) - len(judged),
        "by_type": by_type,
    }
