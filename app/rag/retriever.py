"""Find the chunks most similar in meaning to a question."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.embedder import embed_query
from app.models import LIVE_STATUSES, Chunk, Document


@dataclass(frozen=True)
class RetrievedChunk:
    title: str
    chapter: str | None
    article_no: str
    content: str
    source_url: str
    distance: float
    status: str

    @property
    def citation(self) -> str:
        return f"{self.title} {self.article_no}"


def search(
    session: Session, query: str, top_k: int | None = None, include_history: bool = False
) -> list[RetrievedChunk]:
    """The chunks closest in meaning to the query.

    By default only documents in force or in rulemaking are searched; include_history
    adds past CFR editions and enacting laws, for questions about how a rule used to read.
    """
    vector = embed_query(query)
    distance = Chunk.embedding.cosine_distance(vector)

    statement = (
        select(
            Document.title,
            Chunk.chapter,
            Chunk.article_no,
            Chunk.content,
            Document.source_url,
            distance.label("distance"),
            Document.status,
        )
        .select_from(Chunk)
        .join(Chunk.document)
    )
    if not include_history:
        statement = statement.where(Document.status.in_(LIVE_STATUSES))
    rows = session.execute(statement.order_by(distance).limit(top_k or settings.top_k))
    return [RetrievedChunk(*row) for row in rows]
