"""One JSON line per /chat request: what was asked, found, answered, how long and how costly.

Spec: docs/specs/chat-trace.md
"""

from dataclasses import dataclass


@dataclass
class ChatTrace:
    request_id: str
    timestamp: str
    user_id: int
    question: str | None
    question_chars: int
    include_history: bool
    about_rulemaking: bool
    sources: list[dict]
    model: str
    prompt_version: str
    top_k: int
    retrieval_ms: int
    first_token_ms: int | None
    total_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    llm_queue_ms: int | None
    cost_usd: float | None
    declined: bool
    answer_chars: int
    error: str | None


def prompt_version() -> str:
    raise NotImplementedError


def cost_usd(prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
    raise NotImplementedError


def to_json_line(trace: ChatTrace) -> str:
    raise NotImplementedError


def write_trace(trace: ChatTrace) -> None:
    raise NotImplementedError
