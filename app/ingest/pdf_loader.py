"""Extract text from PDFs and cut it into chunks, one locator per page."""

import json
import pathlib

import pymupdf

from app.config import settings
from app.ingest.chunker import ChunkData

PDF_DIR = pathlib.Path("data/pdf")
MANIFEST = PDF_DIR / "manifest.json"
OCR_DIR = PDF_DIR / "ocr"
MIN_CHARS_PER_PAGE = 50


def load_manifest() -> dict[str, dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


def page_texts(path: pathlib.Path) -> list[str]:
    """Text of each page, from the cached OCR for scans or from the PDF itself."""
    cache = OCR_DIR / f"{path.name}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    with pymupdf.open(path) as doc:
        return [page.get_text("text", sort=True).strip() for page in doc]


def split_page(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]

    parts = []
    start = 0
    while start < len(text):
        parts.append(text[start : start + size])
        start += size - overlap
    return parts


def chunk_pdf(path: pathlib.Path) -> list[ChunkData]:
    chunks: list[ChunkData] = []
    for number, text in enumerate(page_texts(path), start=1):
        # Pages below this are covers, dividers or image-only pages with stray captions.
        if len(text) < MIN_CHARS_PER_PAGE:
            continue

        for part in split_page(text, settings.chunk_size, settings.chunk_overlap):
            chunks.append(
                ChunkData(
                    chunk_index=len(chunks),
                    chapter=None,
                    article_no=f"第 {number} 頁",
                    content=part,
                )
            )
    return chunks
