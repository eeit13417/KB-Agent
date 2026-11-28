"""Tests for stream_answer statistics (docs/specs/chat-trace.md, AC-6 and AC-7)."""

from types import SimpleNamespace

import pytest

import app.rag.generator as generator
from app.config import settings
from app.rag.generator import NO_ANSWER, AnswerStats, stream_answer
from app.rag.retriever import RetrievedChunk


def make_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        title="29 CFR Part 778",
        chapter="Subpart B",
        article_no="§ 778.107",
        content="Overtime is paid at one and one-half times the regular rate.",
        source_url="https://www.ecfr.gov/current/title-29/part-778",
        distance=0.2,
        status="current",
    )


def fake_chunk(text, usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))],
        usage=usage,
    )


class FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return iter(self._chunks)


@pytest.fixture
def groq(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")

    def install(chunks):
        client = FakeClient(chunks)
        monkeypatch.setattr(generator, "get_client", lambda: client)
        return client

    return install


def usage(prompt, completion, queue):
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, queue_time=queue)


def test_stats_filled_from_last_chunk_usage(groq):
    """AC-6: text is yielded as before and AnswerStats holds the last chunk's usage."""
    groq([fake_chunk("Over"), fake_chunk("time", usage(1800, 40, 0.25))])
    stats = AnswerStats()
    tokens = list(stream_answer("What is overtime?", [make_chunk()], stats=stats))
    assert tokens == ["Over", "time"]
    assert stats.prompt_tokens == 1800
    assert stats.completion_tokens == 40
    assert stats.queue_seconds == pytest.approx(0.25)


def test_no_chunks_declines_without_call_and_leaves_stats_none(groq):
    """AC-7: no retrieved chunks -> yields NO_ANSWER, no client call, stats stay None."""
    client = groq([fake_chunk("should not be used")])
    stats = AnswerStats()
    tokens = list(stream_answer("What is overtime?", [], stats=stats))
    assert "".join(tokens) == NO_ANSWER
    assert client.calls == []
    assert stats == AnswerStats(None, None, None)


def test_without_stats_argument_works_as_before(groq):
    """AC-7: without a stats argument stream_answer works as before (decline and normal stream)."""
    client = groq([fake_chunk("Over"), fake_chunk("time", usage(1800, 40, 0.25))])
    assert "".join(stream_answer("What is overtime?", [])) == NO_ANSWER
    assert client.calls == []
    assert list(stream_answer("What is overtime?", [make_chunk()])) == ["Over", "time"]
