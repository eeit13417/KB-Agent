"""Load law JSON files, chunk and embed them, and store them in Postgres.

Safe to re-run: each law is deleted and re-inserted in one transaction.
"""

import json
import logging
import pathlib
import time
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingest.chunker import ChunkData, chunk_law
from app.ingest.embedder import embed_documents
from app.models import Chunk, Document

RAW_DIR = pathlib.Path("data/raw")
logger = logging.getLogger(__name__)


def parse_date(value: str) -> date | None:
    return datetime.strptime(value, "%Y%m%d").date() if value else None


def embedding_text(title: str, chunk: ChunkData) -> str:
    # Article bodies rarely mention the law's name, so prefix it; otherwise a query
    # like "勞基法 特休" gets no help from the "勞基法" part.
    header = f"{title} {chunk.article_no}"
    if chunk.chapter:
        header += f" {chunk.chapter}"
    return f"{header}\n{chunk.content}"


def ingest_law(session: Session, law: dict) -> int:
    title = law["LawName"]
    chunks = chunk_law(law)
    # Embed before touching the database, so a failure here leaves the old data intact.
    vectors = embed_documents([embedding_text(title, c) for c in chunks])

    session.execute(delete(Document).where(Document.title == title))
    session.add(
        Document(
            title=title,
            category=law["LawCategory"],
            source_url=law["LawURL"],
            modified_date=parse_date(law["LawModifiedDate"]),
            chunks=[
                Chunk(
                    chunk_index=c.chunk_index,
                    chapter=c.chapter,
                    article_no=c.article_no,
                    content=c.content,
                    embedding=v,
                )
                for c, v in zip(chunks, vectors, strict=True)
            ],
        )
    )
    return len(chunks)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    paths = sorted(RAW_DIR.glob("*.json"))
    if not paths:
        raise SystemExit(f"no JSON files in {RAW_DIR}; run scripts/fetch_laws.py first")

    started = time.perf_counter()
    total = 0
    for path in paths:
        law = json.loads(path.read_text(encoding="utf-8"))
        with SessionLocal.begin() as session:
            count = ingest_law(session, law)
        total += count
        logger.info("%s: %d chunks", law["LawName"], count)

    with SessionLocal() as session:
        stored = session.scalar(select(func.count()).select_from(Chunk))
    logger.info(
        "done: %d laws, %d chunks in %.1fs (database holds %d chunks)",
        len(paths), total, time.perf_counter() - started, stored,
    )


if __name__ == "__main__":
    main()
