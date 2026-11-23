"""Rank the regulation above rulemaking text for questions about today's rules.

Spec: docs/specs/prefer-regulations.md
"""

from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")

RULEMAKING_PENALTY: float = 0.1
CANDIDATE_POOL: int = 50


def about_rulemaking(question: str) -> bool:
    raise NotImplementedError


def adjusted_distance(distance: float, status: str, prefer_regulations: bool) -> float:
    raise NotImplementedError


def rank(chunks: Sequence[T], question: str, top_k: int) -> list[T]:
    raise NotImplementedError
