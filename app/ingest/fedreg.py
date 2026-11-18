"""Parse Federal Register rules and proposed rules (XML) into chunks.

Spec: docs/specs/fedreg.md
"""

from app.config import settings
from app.ingest.chunker import SourceDocument

KEEP_SINCE: str = "2010-01-01"
OSHA_MAX_PAGES: int = 5


def select_documents(catalog: list[dict]) -> list[dict]:
    raise NotImplementedError


def parse_document(xml: bytes, entry: dict, max_chars: int = settings.chunk_size) -> SourceDocument:
    raise NotImplementedError
