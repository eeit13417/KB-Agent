"""Decide from a question's wording whether to search past versions, and which ones.

Spec: docs/specs/history-routing.md
"""

import re
from dataclasses import dataclass

# Four digits from 1900 to 2099, not part of a longer run of digits.
_YEAR = r"(?<!\d)(?:19|20)\d{2}(?!\d)"
_YEAR_RE = re.compile(_YEAR)

_HISTORY_PATTERNS = [
    # Rule 1: a 20th-century year can only refer to a past version.
    re.compile(r"(?<!\d)19\d{2}(?!\d)"),
    # Rule 2: a year, at most three words, then a word naming a body of rules.
    # The singular "rule" is left out on purpose: it names a Federal Register document.
    re.compile(
        _YEAR + r"(?:\W+\w+){0,3}?\W+(?:rules|regulations|editions?|amendments|act)\b",
        re.IGNORECASE,
    ),
    # Rule 3: "Amendments of 2007", "Act of 2007", "edition of 2005".
    re.compile(r"\b(?:amendments|act|edition)\s+of\s+" + _YEAR, re.IGNORECASE),
    # Rule 4: "enacted in 1996", "before 2019", "prior to 2016".
    re.compile(r"\b(?:enacted\s+in|passed\s+in|before|prior\s+to)\s+" + _YEAR, re.IGNORECASE),
    # Rule 5: words that only make sense about past versions.
    re.compile(r"\b(?:editions?|originally|historically)\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class Scope:
    include_history: bool
    years: tuple[int, ...]


def mentioned_years(question: str) -> list[int]:
    """The distinct years (1900-2099) in the question, in ascending order."""
    return sorted({int(match) for match in _YEAR_RE.findall(question)})


def needs_history(question: str) -> bool:
    """Whether the question's wording asks about past versions of a rule."""
    return any(pattern.search(question) for pattern in _HISTORY_PATTERNS)


def search_scope(question: str, include_history: bool | None = None) -> Scope:
    """What to search for this question; an explicit include_history overrides the wording."""
    if include_history is None:
        include_history = needs_history(question)
    years = tuple(mentioned_years(question)) if include_history else ()
    return Scope(include_history=include_history, years=years)


def title_matches_year(title: str, year: int) -> bool:
    """Whether a document title names a past CFR edition or an enacting law of that year."""
    return f"({year} edition)" in title or f" of {year}" in title
