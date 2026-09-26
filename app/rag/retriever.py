"""Find the chunks most similar in meaning to a question."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.embedder import embed_query
from app.models import Chunk, Document


@dataclass(frozen=True)
class RetrievedChunk:
    title: str
    chapter: str | None
    article_no: str
    content: str
    source_url: str
    distance: float

    @property
    def citation(self) -> str:
        return f"{self.title} {self.article_no}"


def search(session: Session, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
    vector = embed_query(query)
    distance = Chunk.embedding.cosine_distance(vector)

    rows = session.execute(
        select(
            Document.title,
            Chunk.chapter,
            Chunk.article_no,
            Chunk.content,
            Document.source_url,
            distance.label("distance"),
        )
        .select_from(Chunk)
        .join(Chunk.document)
        .order_by(distance)
        .limit(top_k or settings.top_k)
    )
    return [RetrievedChunk(*row) for row in rows]
