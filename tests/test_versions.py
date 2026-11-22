"""Tests for app/rag/versions.py and the retriever's include_history default.

Spec: docs/specs/history-routing.md
"""

import inspect

import pytest

from app.rag.versions import (
    Scope,
    mentioned_years,
    needs_history,
    search_scope,
    title_matches_year,
)

# --- mentioned_years ---------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What changed between the 2005 and 2020 editions?", [2005, 2020]),
        ("In 1979 and again in 1979", [1979]),
        ("How many hours can a 14-year-old work?", []),
    ],
)
def test_mentioned_years_distinct_ascending(question, expected):
    """AC-1: distinct years in ascending order; [] when there are none."""
    assert mentioned_years(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "Pub. L. 95-151 (91 Stat. 1245)",
        "at least 1,250 hours",
        "a $20000 bonus",
        "in 1850",
        "in 2150",
    ],
)
def test_mentioned_years_ignores_non_years(question):
    """AC-2: numbers that are not years are ignored."""
    assert mentioned_years(question) == []


# --- needs_history: true -----------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "What was the minimum wage in 1979?",
        "Has the youth minimum wage changed since it was enacted in 1996?",
    ],
)
def test_needs_history_rule1_twentieth_century_year(question):
    """AC-3: rule 1, a year from 1900 to 1999 means history."""
    assert needs_history(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "Under the 2004 regulations, who counted as a highly compensated employee?",
        "What did the 2008 amendments change?",
        "Under the 2012 OSHA recordkeeping rules, which industries were exempt?",
    ],
)
def test_needs_history_rule2_year_then_rules_word(question):
    """AC-4: rule 2, a year followed within three words by rules/regulations/amendments."""
    assert needs_history(question) is True


def test_needs_history_rule3_act_of_year():
    """AC-5: rule 3, 'Act of <year>' means history."""
    assert (
        needs_history("When did the Fair Minimum Wage Act of 2007 raise the rate to $7.25?")
        is True
    )


@pytest.mark.parametrize(
    "question",
    [
        "What was the HCE threshold before 2019?",
        "What applied prior to 2016?",
    ],
)
def test_needs_history_rule4_before_prior_to_year(question):
    """AC-6: rule 4, 'before' / 'prior to' directly followed by a year."""
    assert needs_history(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "What did the latest edition say about ladders?",
        "How was overtime originally calculated for tipped employees?",
        "Historically, how were farmworkers treated under the FLSA?",
    ],
)
def test_needs_history_rule5_history_words(question):
    """AC-7: rule 5, 'edition' / 'originally' / 'historically' means history."""
    assert needs_history(question) is True


def test_needs_history_case_insensitive():
    """AC-8: case does not matter."""
    assert needs_history("UNDER THE 2004 REGULATIONS, WHO WAS EXEMPT?") is True


# --- needs_history: false ----------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "What is the current federal minimum wage?",
        "How many hours can a 14-year-old work during the school year?",
        "What form is used to record workplace injuries?",
    ],
)
def test_needs_history_false_for_live_questions(question):
    """AC-9: ordinary questions about today's rules do not need history."""
    assert needs_history(question) is False


@pytest.mark.parametrize(
    "question",
    [
        "When did the 2019 overtime final rule take effect?",
        "What does DOL's 2025 proposed rule on joint employment propose?",
        "Is the 2016 rule on overtime still in effect?",
        "What will the salary threshold be in 2028?",
    ],
)
def test_needs_history_false_for_fr_document_or_future_year(question):
    """AC-10: a year naming a Federal Register document or the future is not history."""
    assert needs_history(question) is False


def test_needs_history_rule2_distance_limit():
    """AC-11: rule 2 does not apply with nine words between the year and 'rules'."""
    question = (
        "In 2019 the department, after many public comments and hearings, issued rules"
    )
    assert needs_history(question) is False


def test_needs_history_whole_words_only():
    """AC-12: 'act' inside 'contract' or 'actual' does not match."""
    assert needs_history("Under the 2020 contract, is the actual pay rate enough?") is False


# --- search_scope ------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "Under the 1997 rules, what was the salary test?",
            Scope(include_history=True, years=(1997,)),
        ),
        (
            "What is the current federal minimum wage?",
            Scope(include_history=False, years=()),
        ),
    ],
)
def test_search_scope_automatic(question, expected):
    """AC-13: with include_history=None the scope follows the question's wording."""
    assert search_scope(question) == expected


def test_search_scope_history_without_years():
    """AC-14: history with no year mentioned gives an empty years tuple."""
    assert search_scope("How was overtime originally calculated?") == Scope(
        include_history=True, years=()
    )


@pytest.mark.parametrize(
    ("question", "include_history", "expected"),
    [
        (
            "Under the 1997 rules, what was the salary test?",
            False,
            Scope(include_history=False, years=()),
        ),
        (
            "When did the 2019 overtime final rule take effect?",
            True,
            Scope(include_history=True, years=(2019,)),
        ),
    ],
)
def test_search_scope_explicit_choice_wins(question, include_history, expected):
    """AC-15: an explicit include_history wins over the question's wording."""
    assert search_scope(question, include_history=include_history) == expected


# --- title_matches_year ------------------------------------------------------

_LAW_TITLE = "Pub. L. 89-601, Fair Labor Standards Amendments of 1966 (80 Stat. 830)"


@pytest.mark.parametrize(
    ("title", "year", "expected"),
    [
        ("29 CFR Part 541 (1997 edition)", 1997, True),
        ("29 CFR Part 541 (1997 edition)", 2005, False),
        (_LAW_TITLE, 1966, True),
        (_LAW_TITLE, 1967, False),
        ("29 CFR Part 541", 1997, False),
    ],
)
def test_title_matches_year(title, year, expected):
    """AC-16: past CFR edition titles and enacting-law titles match their year only."""
    assert title_matches_year(title, year) is expected


# --- search (retriever) ------------------------------------------------------


def test_search_include_history_defaults_to_none():
    """AC-17: search's include_history parameter defaults to None."""
    from app.rag.retriever import search

    assert inspect.signature(search).parameters["include_history"].default is None
