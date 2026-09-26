import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.models import User
from app.api.deps import get_db, get_current_user
from app.rag.generator import stream_answer
from app.rag.retriever import search
from app.schemas import Citation, ChatRequest

router = APIRouter()


def sse(payload: dict) -> str:
    # Answers contain newlines, which would break raw SSE framing, so send JSON.
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat")
def chat(request: ChatRequest, session: Session = Depends(get_db), user: User = Depends(get_current_user)) -> StreamingResponse:
    # Retrieve before streaming starts, so the database session is done being used
    # by the time the response body begins.
    chunks = search(session, request.question)
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

    def events() -> Iterator[str]:
        yield sse({"type": "citations", "items": [c.model_dump() for c in citations]})
        for token in stream_answer(request.question, chunks):
            yield sse({"type": "token", "text": token})
        yield sse({"type": "done"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
