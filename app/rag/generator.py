"""Turn retrieved chunks into a streamed, cited answer."""

from collections.abc import Iterator
from functools import lru_cache

from groq import Groq

from app.config import settings
from app.rag.retriever import RetrievedChunk

SYSTEM_PROMPT = """你是台灣勞動法規的客服助理。

規則：
1. 只能根據下方提供的法條回答，不得使用法條以外的知識。
2. 每個論述後面必須標註出處，格式為（勞動基準法 第 38 條）。
3. 提供的法條不足以回答問題時，直接回答「找不到相關資料」，不要推測。
4. 用繁體中文、白話說明，先講結論，再說明依據。"""

NO_ANSWER = "找不到相關資料。"


def build_messages(question: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    context = "\n\n".join(f"[{c.citation}]\n{c.content}" for c in chunks)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"法條：\n{context}\n\n問題：{question}"},
    ]


@lru_cache(maxsize=1)
def get_client() -> Groq:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    return Groq(api_key=settings.groq_api_key)


def stream_answer(question: str, chunks: list[RetrievedChunk]) -> Iterator[str]:
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
