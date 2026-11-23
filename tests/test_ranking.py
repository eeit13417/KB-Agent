"""Tests for app/rag/ranking.py, written from docs/specs/prefer-regulations.md."""

from dataclasses import dataclass

import pytest

from app.models import RULEMAKING
from app.rag.ranking import (
    CANDIDATE_POOL,
    RULEMAKING_PENALTY,
    about_rulemaking,
    adjusted_distance,
    rank,
)


@dataclass(eq=False)
class Chunk:
    """Stand-in for RetrievedChunk: only the attributes rank uses, plus a name."""

    name: str
    distance: float
    status: str


def names(chunks):
    return [c.name for c in chunks]


def six_chunks():
    return [
        Chunk("A", 0.30, RULEMAKING),
        Chunk("B", 0.33, "current"),
        Chunk("C", 0.35, RULEMAKING),
        Chunk("D", 0.38, "superseded"),
        Chunk("E", 0.46, "current"),
        Chunk("F", 0.50, "current"),
    ]


NOT_ABOUT_RULEMAKING = "Do I get paid for on-call time at home?"
ABOUT_RULEMAKING = "Was the overtime salary increase vacated?"


# --- about_rulemaking: true -------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Is the independent contractor rule still in force?",
        "What did the 2019 proposal on the regular rate say?",
        "What has DOL proposed for heat illness?",
        "What does OSHA say the agency proposes for crane operators?",
        "Which rulemaking changed the tip credit?",
    ],
)
def test_about_rulemaking_rule_family(question):
    """AC-1: rule / proposal / proposed / proposes / rulemaking are detected."""
    assert about_rulemaking(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "Which FR Doc announced the change?",
        "What did the Federal Register notice on tip credits say?",
        "When is the comment deadline for the heat standard?",
        "Were comments accepted by email?",
    ],
)
def test_about_rulemaking_fr_and_comment_family(question):
    """AC-2: FR Doc / Federal Register / comment / comments are detected."""
    assert about_rulemaking(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "Was the overtime salary increase vacated by a court?",
        "Can a court vacate a regulation?",
        "Did DOL rescind the joint employer standard?",
        "Was it rescinded?",
        "Is the subminimum wage phase-out still pending?",
    ],
)
def test_about_rulemaking_vacate_rescind_pending_family(question):
    """AC-3: vacate(d) / rescind(ed) / pending are detected."""
    assert about_rulemaking(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "What did the technical amendment correct?",
        "When did OSHA grant final approval to Hawaii's plan?",
        "When does the change take effect?",
        "When it takes effect, who must comply?",
        "When the change took effect, what happened to pending cases?",
    ],
)
def test_about_rulemaking_phrase_family(question):
    """AC-4: technical amendment / final approval / take, takes, took effect are detected."""
    assert about_rulemaking(question) is True


def test_about_rulemaking_case_insensitive():
    """AC-5: case does not matter."""
    assert about_rulemaking("WAS IT VACATED?") is True


# --- about_rulemaking: false ------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "What is the federal minimum wage?",
        "Do I get paid for on-call time at home?",
        "What is the effective rate of pay for a tipped employee?",
    ],
)
def test_about_rulemaking_false_for_ordinary_questions(question):
    """AC-6: ordinary questions about today's rules are not about rulemaking."""
    assert about_rulemaking(question) is False


@pytest.mark.parametrize(
    "question",
    [
        "Under the 1997 rules, what was the salary test?",
        "Can my employer overrule my doctor's note?",
        "Is a sports commentator paid overtime?",
    ],
)
def test_about_rulemaking_whole_words_only(question):
    """AC-7: plural 'rules' and longer words containing an entry do not count."""
    assert about_rulemaking(question) is False


# --- adjusted_distance ------------------------------------------------------


@pytest.mark.parametrize(
    ("distance", "status", "prefer", "expected"),
    [
        (0.30, "rulemaking", True, 0.40),
        (0.30, "rulemaking", False, 0.30),
        (0.30, "current", True, 0.30),
        (0.30, "superseded", True, 0.30),
        (0.30, "enacted", True, 0.30),
    ],
)
def test_adjusted_distance(distance, status, prefer, expected):
    """AC-8: only rulemaking chunks are penalised, and only when preferring regulations."""
    assert adjusted_distance(distance, status, prefer) == pytest.approx(expected)


def test_constants():
    """AC-9: penalty and candidate pool have their specified values."""
    assert RULEMAKING_PENALTY == 0.1
    assert CANDIDATE_POOL == 50


# --- rank -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("top_k", "expected"),
    [
        (3, ["B", "D", "A"]),
        (5, ["B", "D", "A", "C", "E"]),
    ],
)
def test_rank_penalises_rulemaking_for_ordinary_question(top_k, expected):
    """AC-10: for a question not about rulemaking, rulemaking chunks rank as if 0.1 further."""
    assert names(rank(six_chunks(), NOT_ABOUT_RULEMAKING, top_k)) == expected


def test_rank_no_penalty_for_rulemaking_question():
    """AC-11: for a question about rulemaking, chunks rank by real distance."""
    assert names(rank(six_chunks(), ABOUT_RULEMAKING, 3)) == ["A", "B", "C"]


def test_rank_much_closer_rulemaking_chunk_still_wins():
    """AC-12: a rulemaking chunk more than the penalty closer still ranks first."""
    chunks = [Chunk("G", 0.20, RULEMAKING), Chunk("H", 0.35, "current")]
    assert names(rank(chunks, NOT_ABOUT_RULEMAKING, 2)) == ["G", "H"]


@pytest.mark.parametrize(
    "order",
    [["I", "J"], ["J", "I"]],
)
def test_rank_ties_keep_input_order(order):
    """AC-13: chunks with equal adjusted distances keep their input order."""
    chunks = [Chunk(n, 0.40, "current") for n in order]
    assert names(rank(chunks, NOT_ABOUT_RULEMAKING, 2)) == order


def test_rank_returns_all_input_objects_unchanged():
    """AC-14: top_k larger than the input returns all; input and objects are unchanged."""
    chunks = six_chunks()
    snapshot = list(chunks)
    distances = {id(c): c.distance for c in chunks}

    result = rank(chunks, NOT_ABOUT_RULEMAKING, 10)

    assert len(result) == 6
    assert chunks == snapshot
    assert len(chunks) == 6
    assert all(a is b for a, b in zip(chunks, snapshot))
    input_ids = {id(c) for c in chunks}
    assert {id(r) for r in result} == input_ids
    for r in result:
        assert r.distance == distances[id(r)]


def test_rank_empty_input():
    """AC-14: an empty input gives an empty list."""
    assert rank([], "anything", 5) == []
