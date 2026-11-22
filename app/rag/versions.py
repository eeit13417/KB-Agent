"""Decide from a question's wording whether to search past versions, and which ones.

Spec: docs/specs/history-routing.md
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    include_history: bool
    years: tuple[int, ...]


def mentioned_years(question: str) -> list[int]:
    raise NotImplementedError


def needs_history(question: str) -> bool:
    raise NotImplementedError


def search_scope(question: str, include_history: bool | None = None) -> Scope:
    raise NotImplementedError


def title_matches_year(title: str, year: int) -> bool:
    raise NotImplementedError
