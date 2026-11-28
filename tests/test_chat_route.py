"""Tests for the /api/chat trace (docs/specs/chat-trace.md, AC-8 to AC-12)."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.routes_chat as routes_chat
from app.api.deps import get_current_user, get_db
from app.config import settings
from app.main import app
from app.rag.generator import NO_ANSWER
from app.rag.retriever import RetrievedChunk

QUESTION = "What is the overtime salary threshold?"
TOKENS = ["The threshold ", "is $684 ", "per week."]
PROMPT_TOKENS = 1800
COMPLETION_TOKENS = 40
QUEUE_SECONDS = 0.25

CHUNKS = [
    RetrievedChunk(
        title="29 CFR Part 541",
        chapter="Subpart G",
        article_no="§ 541.600",
        content="An employee must be compensated on a salary basis...",
        source_url="https://www.ecfr.gov/current/title-29/part-541",
        distance=0.21,
        status="current",
    ),
    RetrievedChunk(
        title="Defining and Delimiting the Exemptions",
        chapter=None,
        article_no="",
        content="The Department proposes to update the salary level...",
        source_url="https://www.federalregister.gov/d/2023-19032",
        distance=0.34,
        status="rulemaking",
    ),
]


def make_stream(tokens, error=None):
    def fake_stream_answer(question, chunks, stats=None):
        if stats is not None:
            stats.prompt_tokens = PROMPT_TOKENS
            stats.completion_tokens = COMPLETION_TOKENS
            stats.queue_seconds = QUEUE_SECONDS
        for token in tokens:
            yield token
        if error is not None:
            raise error

    return fake_stream_answer


@pytest.fixture
def env(monkeypatch):
    traces = []
    monkeypatch.setattr(settings, "trace_questions", False)
    monkeypatch.setattr(settings, "trace_file", "")
    monkeypatch.setattr(settings, "input_per_million", 0.15)
    monkeypatch.setattr(settings, "output_per_million", 0.60)
    monkeypatch.setattr(routes_chat, "search", lambda *args, **kwargs: list(CHUNKS))
    monkeypatch.setattr(routes_chat, "stream_answer", make_stream(TOKENS))
    monkeypatch.setattr(routes_chat, "write_trace", traces.append)

    def fake_db():
        yield None

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, email="owner@example.com")
    yield SimpleNamespace(traces=traces, monkeypatch=monkeypatch)
    app.dependency_overrides.clear()


def post(question=QUESTION, raise_server_exceptions=True):
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    return client.post("/api/chat", json={"question": question})


def events(response):
    return [
        json.loads(line[len("data: "):])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_one_trace_and_request_id_header(env):
    """AC-8: one trace per request, X-Request-ID equals its request_id, SSE events unchanged."""
    response = post()
    assert response.status_code == 200
    assert len(env.traces) == 1
    trace = env.traces[0]
    assert response.headers.get("X-Request-ID") == trace.request_id

    evs = events(response)
    assert evs[0]["type"] == "citations"
    assert [(c["title"], c["article_no"]) for c in evs[0]["items"]] == [
        (c.title, c.article_no) for c in CHUNKS
    ]
    assert [e["text"] for e in evs[1:-1]] == TOKENS
    assert all(e["type"] == "token" for e in evs[1:-1])
    assert evs[-1] == {"type": "done"}


def test_trace_contents(env):
    """AC-9: user, sources, lengths, token counts and cost, declined, error, timings."""
    post()
    assert len(env.traces) == 1
    trace = env.traces[0]
    assert trace.user_id == 7
    assert trace.sources == [
        {"title": c.title, "article_no": c.article_no, "status": c.status, "distance": c.distance}
        for c in CHUNKS
    ]
    assert trace.question_chars == len(QUESTION)
    assert trace.answer_chars == len("".join(TOKENS))
    assert trace.prompt_tokens == PROMPT_TOKENS
    assert trace.completion_tokens == COMPLETION_TOKENS
    assert trace.llm_queue_ms == 250
    expected_cost = PROMPT_TOKENS * 0.15 / 1e6 + COMPLETION_TOKENS * 0.60 / 1e6
    assert trace.cost_usd == pytest.approx(expected_cost)
    assert trace.declined is False
    assert trace.error is None
    assert trace.total_ms >= trace.retrieval_ms >= 0


def test_question_hidden_by_default(env):
    """AC-10: question is None when trace_questions is false."""
    post()
    assert len(env.traces) == 1
    assert env.traces[0].question is None


def test_question_kept_when_enabled(env):
    """AC-10: question is the text when trace_questions is true."""
    env.monkeypatch.setattr(settings, "trace_questions", True)
    post()
    assert len(env.traces) == 1
    assert env.traces[0].question == QUESTION


def test_declined_when_answer_is_no_answer(env):
    """AC-11: declined is true when the answer is exactly NO_ANSWER."""
    env.monkeypatch.setattr(routes_chat, "stream_answer", make_stream([NO_ANSWER]))
    post()
    assert len(env.traces) == 1
    assert env.traces[0].declined is True


def test_stream_error_is_traced(env):
    """AC-12: RuntimeError after one token -> one trace with the error and first_token_ms set."""
    env.monkeypatch.setattr(
        routes_chat, "stream_answer", make_stream(["Partial "], error=RuntimeError("boom"))
    )
    try:
        post(raise_server_exceptions=False)
    except RuntimeError:
        pass  # the spec allows the exception to surface; the trace must exist either way
    assert len(env.traces) == 1
    trace = env.traces[0]
    assert trace.error == "RuntimeError: boom"
    assert trace.first_token_ms is not None
    assert trace.first_token_ms >= 0


def test_trace_scope_identity_and_settings_fields(env):
    """AC-13: history/rulemaking question -> both flags true; id, timestamp, model, top_k, prompt_version."""
    import re

    from app.trace import prompt_version

    question = "Under the 1997 rules, was a change proposed?"
    post(question)
    assert len(env.traces) == 1
    trace = env.traces[0]
    assert trace.include_history is True
    assert trace.about_rulemaking is True
    assert re.fullmatch(r"[0-9a-f]{32}", trace.request_id)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", trace.timestamp)
    assert trace.model == settings.groq_model
    assert trace.top_k == settings.top_k
    assert trace.prompt_version == prompt_version()


def test_trace_scope_flags_false_for_plain_question(env):
    """AC-13: "What is the minimum wage?" -> include_history and about_rulemaking both false."""
    post("What is the minimum wage?")
    assert len(env.traces) == 1
    trace = env.traces[0]
    assert trace.include_history is False
    assert trace.about_rulemaking is False
