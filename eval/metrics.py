"""The five evaluation numbers, computed from per-question results.

Spec: docs/specs/metrics.md
"""

Source = tuple[str, str]  # (document title, article_no)

VERDICTS: tuple[str, ...] = ("correct", "partial", "incorrect")


def parse_sources(text: str) -> list[Source]:
    raise NotImplementedError


def source_hit(expected: list[Source], retrieved: list[Source], k: int = 5) -> bool:
    raise NotImplementedError


def document_hit(expected: list[Source], retrieved: list[Source], k: int = 5) -> bool:
    raise NotImplementedError


def percentile(values: list[float], p: float) -> float:
    raise NotImplementedError


def query_cost(
    prompt_tokens: int, completion_tokens: int, input_per_million: float, output_per_million: float
) -> float:
    raise NotImplementedError


def summarize(results: list[dict]) -> dict:
    raise NotImplementedError
