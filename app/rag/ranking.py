"""Rank the regulation above rulemaking text for questions about today's rules.

Spec: docs/specs/prefer-regulations.md
"""

import re
from collections.abc import Sequence
from typing import Protocol, TypeVar

from app.models import RULEMAKING
from app.rag.versions import needs_history

RULEMAKING_PENALTY: float = 0.1
CANDIDATE_POOL: int = 50

# Words and phrases that mark a question as being about rulemaking. Matched as whole
# words, case-insensitively; "rule" is the singular only ("rules" means a past edition).
_RULEMAKING_TERMS = (
    "rulemaking",
    "rule",
    "proposal",
    "proposed",
    "proposes",
    "FR Doc",
    "Federal Register",
    "comment",
    "comments",
    "vacate",
    "vacated",
    "rescind",
    "rescinded",
    "pending",
    "technical amendment",
    "final approval",
    "take effect",
    "takes effect",
    "took effect",
)

_RULEMAKING_PATTERN = re.compile(
    r"(?<!\w)(?:"
    + "|".join(r"\s+".join(map(re.escape, term.split())) for term in _RULEMAKING_TERMS)
    + r")(?!\w)",
    re.IGNORECASE,
)


class _Ranked(Protocol):
    distance: float
    status: str


T = TypeVar("T", bound=_Ranked)


def about_rulemaking(question: str) -> bool:
    """Whether the question's wording asks about rulemaking rather than today's rules."""
    return _RULEMAKING_PATTERN.search(question) is not None


def adjusted_distance(distance: float, status: str, prefer_regulations: bool) -> float:
    """The distance used for ranking: rulemaking chunks are pushed back when preferring
    regulations."""
    if prefer_regulations and status == RULEMAKING:
        return distance + RULEMAKING_PENALTY
    return distance


def rank(chunks: Sequence[T], question: str, top_k: int) -> list[T]:
    """The top_k chunks by adjusted distance (stable), as the same unchanged objects."""
    # Rulemaking text is the evidence of how a rule changed, so questions about past
    # versions keep it in place too (amendment 1).
    prefer_regulations = not about_rulemaking(question) and not needs_history(question)
    ordered = sorted(
        chunks,
        key=lambda c: adjusted_distance(c.distance, c.status, prefer_regulations),
    )
    return ordered[:top_k]
