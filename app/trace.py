"""One JSON line per /chat request: what was asked, found, answered, how long and how costly.

Spec: docs/specs/chat-trace.md
"""

import dataclasses
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.rag import generator

logger = logging.getLogger(__name__)


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
    """A version that changes with every edit of the system prompt."""
    # Read through the module so the current prompt is hashed, not one captured at import.
    return hashlib.sha256(generator.SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


def cost_usd(prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
    """The answer's price in USD at the configured per-million-token prices."""
    if prompt_tokens is None or completion_tokens is None:
        return None
    return (
        prompt_tokens * settings.input_per_million / 1e6
        + completion_tokens * settings.output_per_million / 1e6
    )


def to_json_line(trace: ChatTrace) -> str:
    """The trace as one line of JSON, keys in field order, without a trailing newline."""
    # json.dumps escapes newlines inside strings, so the line never contains one.
    return json.dumps(dataclasses.asdict(trace), ensure_ascii=False)


def write_trace(trace: ChatTrace) -> None:
    """Print the trace to stdout (Cloud Logging) and append it to settings.trace_file if set.

    Never raises: a trace that cannot be written must not fail the request.
    """
    try:
        line = to_json_line(trace)
    except Exception:
        logger.warning("could not serialize trace %s", trace.request_id, exc_info=True)
        return

    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception:
        logger.warning("could not write trace %s to stdout", trace.request_id, exc_info=True)

    if not settings.trace_file:
        return
    try:
        path = Path(settings.trace_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        logger.warning(
            "could not append trace %s to %s", trace.request_id, settings.trace_file, exc_info=True
        )
