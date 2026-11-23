"""Find the chunks most similar in meaning to a question."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.embedder import embed_query
from app.models import LIVE_STATUSES, Chunk, Document
from app.rag.ranking import CANDIDATE_POOL, rank
from app.rag.versions import search_scope, title_matches_year


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
    session: Session,
    query: str,
    top_k: int | None = None,
    include_history: bool | None = None,
) -> list[RetrievedChunk]:
    """The chunks closest in meaning to the query.

    Documents in force or in rulemaking are always searched. Past CFR editions and
    enacting laws are added when the query's wording asks about the past (or when
    include_history is True); if it names years, only those years' editions and laws.
    Within that scope the CANDIDATE_POOL closest chunks are re-ranked so that, unless the
    query is about rulemaking, regulation sections win over nearly-as-close rulemaking text.
    """
    scope = search_scope(query, include_history)
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
    if not scope.include_history:
        statement = statement.where(Document.status.in_(LIVE_STATUSES))
    elif scope.years:
        statement = statement.where(
            Document.status.in_(LIVE_STATUSES)
            | Document.id.in_(_past_documents_of(session, scope.years))
        )
    rows = session.execute(statement.order_by(distance).limit(CANDIDATE_POOL))
    candidates = [RetrievedChunk(*row) for row in rows]
    return rank(candidates, query, top_k or settings.top_k)


def _past_documents_of(session: Session, years: tuple[int, ...]) -> list[int]:
    """Ids of the past editions and enacting laws whose title names one of the years."""
    rows = session.execute(
        select(Document.id, Document.title).where(Document.status.not_in(LIVE_STATUSES))
    )
    return [
        doc_id for doc_id, title in rows if any(title_matches_year(title, y) for y in years)
    ]
