"""Load every source, chunk and embed it, and store it in Postgres.

Safe to re-run: each document is deleted and re-inserted in one transaction.
"""

import dataclasses
import json
import logging
import pathlib
import time
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingest.chunker import ChunkData, SourceDocument
from app.ingest.ecfr import chunk_part
from app.ingest.fedreg import parse_document
from app.ingest.embedder import embed_documents
from app.ingest.govinfo import parse_cfr_part, parse_statute
from app.ingest.pdf_loader import PDF_DIR, chunk_pdf, load_manifest
from app.models import CURRENT, ENACTED, RULEMAKING, SUPERSEDED, Chunk, Document

ECFR_DIR = pathlib.Path("data/raw/ecfr")
FR_DIR = pathlib.Path("data/raw/fr")
GOVINFO_DIR = pathlib.Path("data/raw/govinfo")
logger = logging.getLogger(__name__)


def load_ecfr() -> list[SourceDocument]:
    index_path = ECFR_DIR / "index.json"
    if not index_path.exists():
        raise SystemExit(f"{index_path} not found; run scripts/fetch_ecfr.py first")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    issued = date.fromisoformat(index["date"])

    documents = []
    for path in sorted(ECFR_DIR.glob("part-*.xml")):
        part = chunk_part(path.read_bytes())
        documents.append(
            SourceDocument(
                title=f"29 CFR Part {part.number}",
                category=index["topics"][part.number],
                source_url=f"https://www.ecfr.gov/current/title-29/part-{part.number}",
                modified_date=issued,
                chunks=part.chunks,
                status=CURRENT,
            )
        )
    return documents


def load_fedreg() -> list[SourceDocument]:
    selected_path = FR_DIR / "selected.json"
    if not selected_path.exists():
        raise SystemExit(f"{selected_path} not found; run scripts/fetch_fr.py first")
    entries = json.loads(selected_path.read_text(encoding="utf-8"))

    documents, empty = [], 0
    for entry in entries:
        xml = (FR_DIR / "xml" / f"{entry['document_number']}.xml").read_bytes()
        doc = parse_document(xml, entry)
        # Corrections whose only content is an amendment instruction have no chunks;
        # storing them would leave documents that can never be retrieved.
        if doc.chunks:
            documents.append(dataclasses.replace(doc, status=RULEMAKING))
        else:
            empty += 1
    logger.info("Federal Register: %d documents, %d skipped with no content", len(documents), empty)
    return documents


def load_govinfo() -> list[SourceDocument]:
    selected_path = GOVINFO_DIR / "selected.json"
    if not selected_path.exists():
        raise SystemExit(f"{selected_path} not found; run scripts/fetch_govinfo.py first")
    entries = json.loads(selected_path.read_text(encoding="utf-8"))

    documents = []
    for entry in entries:
        pdf = (GOVINFO_DIR / entry["file"]).read_bytes()
        if entry["kind"] == "cfr":
            doc = dataclasses.replace(parse_cfr_part(pdf, entry), status=SUPERSEDED)
        else:
            doc = dataclasses.replace(parse_statute(pdf, entry), status=ENACTED)
        documents.append(doc)
    logger.info("govinfo: %d documents", len(documents))
    return documents


def load_pdfs() -> list[SourceDocument]:
    manifest = load_manifest()
    documents = []
    for path in sorted(PDF_DIR.glob("*.pdf")):
        entry = manifest.get(path.name, {})
        chunks = chunk_pdf(path)
        if chunks:
            documents.append(
                SourceDocument(
                    title=entry.get("title") or path.stem,
                    category=entry.get("category", "Publications"),
                    source_url=entry.get("source_url", ""),
                    modified_date=None,
                    chunks=chunks,
                )
            )
    return documents


def embedding_text(title: str, chunk: ChunkData) -> str:
    # Prefix where the chunk sits: section text rarely repeats its part's name, so a
    # query like "overtime for retail stores" would get no help from Part 779's title.
    header = f"{title} {chunk.article_no}"
    if chunk.chapter:
        header += f" {chunk.chapter}"
    return f"{header}\n{chunk.content}"


def store(session: Session, doc: SourceDocument, vectors: list[list[float]]) -> None:
    session.execute(delete(Document).where(Document.title == doc.title))
    session.add(
        Document(
            title=doc.title,
            category=doc.category,
            source_url=doc.source_url,
            modified_date=doc.modified_date,
            status=doc.status,
            chunks=[
                Chunk(
                    chunk_index=c.chunk_index,
                    chapter=c.chapter,
                    article_no=c.article_no,
                    content=c.content,
                    embedding=v,
                )
                for c, v in zip(doc.chunks, vectors, strict=True)
            ],
        )
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    started = time.perf_counter()

    documents = load_ecfr() + load_fedreg() + load_govinfo() + load_pdfs()

    # One encode call for all chunks: the model sorts by length internally, so batching
    # across documents wastes much less padding than one call per document.
    texts = [embedding_text(d.title, c) for d in documents for c in d.chunks]
    vectors = embed_documents(texts)
    logger.info("embedded %d chunks in %.1fs", len(texts), time.perf_counter() - started)

    offset = 0
    for doc in documents:
        with SessionLocal.begin() as session:
            store(session, doc, vectors[offset : offset + len(doc.chunks)])
        offset += len(doc.chunks)
        logger.info("%s: %d chunks", doc.title, len(doc.chunks))

    with SessionLocal() as session:
        stored = session.scalar(select(func.count()).select_from(Chunk))
    logger.info(
        "done: %d documents, %d chunks in %.1fs (database holds %d chunks)",
        len(documents), len(texts), time.perf_counter() - started, stored,
    )


if __name__ == "__main__":
    main()
