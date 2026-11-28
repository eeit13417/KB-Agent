import json
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.models import User
from app.api.deps import get_db, get_current_user
from app.config import settings
from app.rag.generator import NO_ANSWER, AnswerStats, stream_answer
from app.rag.ranking import about_rulemaking
from app.rag.retriever import search
from app.rag.versions import search_scope
from app.schemas import Citation, ChatRequest
from app.trace import ChatTrace, cost_usd, prompt_version, write_trace

router = APIRouter()


def sse(payload: dict) -> str:
    # Answers contain newlines, which would break raw SSE framing, so send JSON.
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def _utc_timestamp(at: datetime) -> str:
    # ISO 8601 with milliseconds and Z, for example 2026-11-27T08:15:02.123Z
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"


@router.post("/chat")
def chat(request: ChatRequest, session: Session = Depends(get_db), user: User = Depends(get_current_user)) -> StreamingResponse:
    arrived = time.perf_counter()
    arrived_at = datetime.now(timezone.utc)
    request_id = uuid.uuid4().hex
    question = request.question

    # Retrieve before streaming starts, so the database session is done being used
    # by the time the response body begins.
    search_started = time.perf_counter()
    chunks = search(session, question)
    retrieval_ms = _ms(time.perf_counter() - search_started)
    citations = [
        Citation(
            title=c.title,
            article_no=c.article_no,
            chapter=c.chapter,
            source_url=c.source_url,
            distance=c.distance,
        )
        for c in chunks
    ]
    user_id = user.id

    def build_trace(answer: str, first_token_ms: int | None, stats: AnswerStats, error: str | None) -> ChatTrace:
        return ChatTrace(
            request_id=request_id,
            timestamp=_utc_timestamp(arrived_at),
            user_id=user_id,
            question=question if settings.trace_questions else None,
            question_chars=len(question),
            include_history=search_scope(question).include_history,
            about_rulemaking=about_rulemaking(question),
            sources=[
                {"title": c.title, "article_no": c.article_no, "status": c.status, "distance": c.distance}
                for c in chunks
            ],
            model=settings.groq_model,
            prompt_version=prompt_version(),
            top_k=settings.top_k,
            retrieval_ms=retrieval_ms,
            first_token_ms=first_token_ms,
            total_ms=_ms(time.perf_counter() - arrived),
            prompt_tokens=stats.prompt_tokens,
            completion_tokens=stats.completion_tokens,
            llm_queue_ms=None if stats.queue_seconds is None else _ms(stats.queue_seconds),
            cost_usd=cost_usd(stats.prompt_tokens, stats.completion_tokens),
            declined=answer == NO_ANSWER,
            answer_chars=len(answer),
            error=error,
        )

    def events() -> Iterator[str]:
        stats = AnswerStats()
        parts: list[str] = []
        first_token_ms: int | None = None
        error: str | None = None
        try:
            yield sse({"type": "citations", "items": [c.model_dump() for c in citations]})
            for token in stream_answer(question, chunks, stats=stats):
                if first_token_ms is None:
                    first_token_ms = _ms(time.perf_counter() - arrived)
                parts.append(token)
                yield sse({"type": "token", "text": token})
            yield sse({"type": "done"})
        except GeneratorExit:
            error = "client disconnected"
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            # One trace per request, however the stream ended; write_trace never raises.
            write_trace(build_trace("".join(parts), first_token_ms, stats, error))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-ID": request_id},
    )
