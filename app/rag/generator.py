"""Turn retrieved chunks into a streamed, cited answer."""

from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

from groq import Groq

from app.config import settings
from app.rag.retriever import RetrievedChunk

SYSTEM_PROMPT = """You are a support assistant for U.S. federal labor regulations.

Rules:
1. Answer only from the excerpts provided. Do not use any other knowledge.
2. After every claim, cite its excerpt using the label shown in square brackets,
   for example (29 CFR Part 785 § 785.11).
3. If the excerpts are not enough to answer, reply exactly: "I couldn't find this in the
   knowledge base." Do not guess.
4. Write in plain English. Give the conclusion first, then the supporting rules."""

NO_ANSWER = "I couldn't find this in the knowledge base."



def build_messages(question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    context = "\n\n".join(f"[{c.citation}]\n{c.content}" for c in chunks)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Excerpts:\n{context}\n\nQuestion: {question}"},

    ]


@lru_cache(maxsize=1)
def get_client() -> Groq:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    return Groq(api_key=settings.groq_api_key)


@dataclass
class AnswerStats:
    """Token usage of one answer, filled in by stream_answer (docs/specs/chat-trace.md)."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    queue_seconds: float | None = None


def stream_answer(
    question: str, chunks: list[RetrievedChunk], stats: AnswerStats | None = None
) -> Iterator[str]:
    if settings.llm_provider != "groq":
        raise ValueError(f"unsupported LLM_PROVIDER: {settings.llm_provider}")

    # Nothing retrieved means nothing to ground an answer on; don't spend quota asking.
    if not chunks:
        yield NO_ANSWER
        return

    stream = get_client().chat.completions.create(
        model=settings.groq_model,
        messages=build_messages(question, chunks),
        stream=True,
        temperature=0.2,
    )
    for chunk in stream:
        text = chunk.choices[0].delta.content
        if text:
            yield text
